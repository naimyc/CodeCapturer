"""Turn a screenshot of code into text with Tesseract.

The preprocessing exists to undo the two things that make editor screenshots
hard for OCR:

* **syntax highlighting.** A plain luminance conversion flattens saturated
  keyword colours towards the background. Taking the min (or max, on a dark
  theme) channel keeps every highlight colour far away from the background.
* **screen resolution.** Tesseract's LSTM wants roughly 30px tall text. A fixed
  scale factor over- or under-shoots depending on the display, so the scale is
  derived from the measured text line height instead.

Note there is deliberately no ``tessedit_char_whitelist``: in LSTM mode a
whitelist that omits the space character makes Tesseract drop *every* space.
"""

import shutil

import pytesseract
from PIL import Image, ImageChops, ImageGrab, ImageOps

pytesseract.pytesseract.tesseract_cmd = (
    shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

#: Ink-band height, in pixels, that Tesseract's LSTM engine reads best. Tuned by
#: sweeping this value over the sample screenshots in ``c_images/``.
TARGET_LINE_HEIGHT = 18

#: Clamp on the derived scale factor, so we never blow up a huge screenshot.
MIN_SCALE, MAX_SCALE = 1.0, 4.0

#: White margin added around the image; Tesseract mis-reads glyphs at the edge.
BORDER = 24


def _as_image(source):
    """Accept a PIL image, a path, or a ``(x1, y1, x2, y2)`` screen region."""
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    if isinstance(source, (tuple, list)) and len(source) == 4:
        return ImageGrab.grab(bbox=tuple(source)).convert("RGB")
    return Image.open(source).convert("RGB")


def _background_is_dark(img):
    hist = ImageOps.grayscale(img).histogram()
    return max(range(256), key=lambda i: hist[i]) < 128


def to_gray(img):
    """Flatten to grayscale as dark text on a light background.

    Uses the per-pixel extreme channel rather than luminance so that saturated
    syntax colours (blue keywords, red strings) stay high-contrast.
    """
    r, g, b = img.split()
    if _background_is_dark(img):
        brightest = ImageChops.lighter(ImageChops.lighter(r, g), b)
        return ImageOps.invert(brightest)
    return ImageChops.darker(ImageChops.darker(r, g), b)


def _content_threshold(gray):
    hist = gray.histogram()
    background = max(range(256), key=lambda i: hist[i])
    return max(8, background - 60)


def trim_margins(gray, margin=8):
    """Crop away uniform background around the code."""
    threshold = _content_threshold(gray)
    mask = gray.point(lambda p: 255 if p < threshold else 0, mode="L")
    box = mask.getbbox()
    if not box:
        return gray
    left, upper, right, lower = box
    return gray.crop((max(0, left - margin), max(0, upper - margin),
                      min(gray.width, right + margin),
                      min(gray.height, lower + margin)))


def _row_ink(gray):
    """Per-row proportion of dark pixels, scaled to 0..255.

    Measuring *ink coverage* rather than row brightness keeps the result
    independent of how much text a given line happens to contain -- a short
    line of code is just as much a text row as a full one.
    """
    threshold = _content_threshold(gray)
    mask = gray.point(lambda p: 255 if p < threshold else 0, mode="L")
    return list(mask.resize((1, gray.height), Image.BOX).getdata())


def text_line_height(gray):
    """Median height of the horizontal bands that contain text, in pixels."""
    rows = _row_ink(gray)
    if not rows or max(rows) == 0:
        return 0
    threshold = max(2, max(rows) * 0.05)

    runs, current = [], 0
    for value in rows:
        if value > threshold:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    if not runs:
        return 0
    runs.sort()
    return runs[len(runs) // 2]


def preprocess(source, target_height=TARGET_LINE_HEIGHT, border=BORDER):
    """Return the grayscale image that is actually handed to Tesseract."""
    gray = trim_margins(to_gray(_as_image(source)))

    line_height = text_line_height(gray)
    scale = target_height / line_height if line_height else 2.0
    scale = max(MIN_SCALE, min(MAX_SCALE, scale))
    if scale > 1.01:
        gray = gray.resize((round(gray.width * scale), round(gray.height * scale)),
                           Image.LANCZOS)

    gray = ImageOps.autocontrast(gray)
    return ImageOps.expand(gray, border=border, fill=255)


def _median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else 0


def _fit_char_width(offsets, initial):
    """Find the monospace advance that the measured word starts line up on.

    Tesseract reports the inked width of a word, which is a little narrower than
    the font's advance, so ``width / len(word)`` under-estimates and every column
    drifts by a space or two. Because the source is monospaced, the true advance
    is the one that puts every word start closest to a whole number of columns,
    so fit it directly. The search stays near the initial estimate; half the true
    advance would fit just as well and must stay out of range.
    """
    offsets = [o for o in offsets if o > 0]
    if not offsets or initial <= 0:
        return max(initial, 1)

    best, best_error = initial, None
    for step in range(121):
        candidate = initial * (0.90 + 0.005 * step)  # 0.90 .. 1.50
        error = sum(abs(o / candidate - round(o / candidate)) for o in offsets)
        if best_error is None or error < best_error:
            best, best_error = candidate, error
    return best


def _layout_text(data, max_blank_lines=2):
    """Rebuild the page from word boxes, keeping indentation and blank lines.

    ``image_to_string`` throws away vertical gaps, so blank lines between
    functions are lost. Word coordinates keep them, and they also give a more
    faithful indentation than Tesseract's own space padding.
    """
    lines = {}
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        try:
            if float(data["conf"][i]) < 0:
                continue
        except (TypeError, ValueError):
            pass
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        entry = lines.setdefault(key, {"top": data["top"][i], "words": []})
        entry["top"] = min(entry["top"], data["top"][i])
        entry["words"].append((data["left"][i], word, data["width"][i]))

    if not lines:
        return ""

    ordered = sorted(lines.values(), key=lambda e: e["top"])

    every_word = [word for entry in ordered for word in entry["words"]]
    char_width = _median([w / len(t) for _, t, w in every_word if t]) or 1
    origin = min(left for left, _, _ in every_word)
    char_width = _fit_char_width([left - origin for left, _, _ in every_word],
                                 char_width)
    pitch = _median([b["top"] - a["top"] for a, b in zip(ordered, ordered[1:])])

    out = []
    previous_top = None
    for entry in ordered:
        if previous_top is not None and pitch > 0:
            blanks = int(round((entry["top"] - previous_top) / pitch)) - 1
            out.extend([""] * max(0, min(blanks, max_blank_lines)))
        previous_top = entry["top"]

        line = ""
        for left, word, _ in sorted(entry["words"]):
            column = max(0, round((left - origin) / char_width))
            if column > len(line):
                line += " " * (column - len(line))
            elif line and not line.endswith(" "):
                line += " "
            line += word
        out.append(line.rstrip())
    return "\n".join(out)


def readImage(source, psm=6, tesseract_lang="eng",
              target_height=TARGET_LINE_HEIGHT, layout=True):
    """OCR a screenshot of code and return the raw recognised text.

    `source` may be a PIL image, a file path, or a screen bounding box.
    Set `layout=False` to use Tesseract's own line rendering instead of
    rebuilding the page from word boxes.
    """
    image = preprocess(source, target_height=target_height)
    config = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1"

    if not layout:
        return pytesseract.image_to_string(image, lang=tesseract_lang, config=config)

    data = pytesseract.image_to_data(
        image, lang=tesseract_lang, config=config,
        output_type=pytesseract.Output.DICT,
    )
    text = _layout_text(data)
    if text.strip():
        return text
    # nothing usable came back with coordinates; fall back to plain rendering
    return pytesseract.image_to_string(image, lang=tesseract_lang, config=config)


def readTextFromImage(img):
    """Backwards-compatible alias for :func:`readImage`."""
    return readImage(img)
