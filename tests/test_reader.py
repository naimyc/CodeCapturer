"""End-to-end OCR accuracy tests. Skipped when Tesseract is not installed.

The thresholds are regression guards, not targets: the pipeline currently sits
around 99.9% on these fixtures, so a drop below 97% means something broke.
"""

import difflib
import os
import re
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAS_TESSERACT = shutil.which("tesseract") is not None

if HAS_TESSERACT:
    from PIL import Image

    from src.fix_text import detect_language, fix_code
    from src.reader import preprocess, readImage, text_line_height, to_gray, trim_margins

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
IMAGES = os.path.join(os.path.dirname(HERE), "c_images")

#: (image, expected text, expected language)
CASES = [
    (os.path.join(IMAGES, "screenshot_0.png"),
     os.path.join(DATA, "screenshot_0.expected.txt"), "c"),
    (os.path.join(IMAGES, "screenshot_1.png"),
     os.path.join(DATA, "screenshot_1.expected.txt"), "c"),
    (os.path.join(DATA, "vhdl_dark.png"),
     os.path.join(DATA, "vhdl_dark.expected.txt"), "vhdl"),
    (os.path.join(DATA, "vhdl_light.png"),
     os.path.join(DATA, "vhdl_light.expected.txt"), "vhdl"),
]

#: Identifiers ending in a digit, which Tesseract reads as `l` / `i` / `I`.
#: Held apart from CASES because the samples are deliberately adversarial.
DIGIT_CASES = [
    (os.path.join(DATA, "vhdl_states_dark.png"),
     os.path.join(DATA, "vhdl_states_dark.expected.txt")),
    (os.path.join(DATA, "vhdl_states_light.png"),
     os.path.join(DATA, "vhdl_states_light.expected.txt")),
]

MIN_SIMILARITY = 0.97


def _normalise(text):
    """Compare content, not indentation -- re-indentation is intentional."""
    return "\n".join(re.sub(r"[ \t]+", " ", line.strip())
                     for line in text.splitlines() if line.strip())


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


@unittest.skipUnless(HAS_TESSERACT, "tesseract is not installed")
class TestOcrAccuracy(unittest.TestCase):
    def test_each_sample_is_read_accurately(self):
        for image_path, expected_path, _lang in CASES:
            with self.subTest(image=os.path.basename(image_path)):
                got = fix_code(readImage(image_path))
                want = _read(expected_path)
                ratio = difflib.SequenceMatcher(
                    None, _normalise(got), _normalise(want)).ratio()
                self.assertGreaterEqual(
                    ratio, MIN_SIMILARITY,
                    f"only {ratio:.1%} similar\n--- got ---\n{got}")

    def test_language_is_detected_from_the_image(self):
        for image_path, _expected, lang in CASES:
            with self.subTest(image=os.path.basename(image_path)):
                self.assertEqual(detect_language(readImage(image_path)), lang)

    def test_underscores_survive_in_vhdl(self):
        text = fix_code(readImage(os.path.join(DATA, "vhdl_dark.png")))
        for name in ("std_logic_vector", "rising_edge", "reset_n",
                     "STD_LOGIC_1164", "NUMERIC_STD"):
            self.assertIn(name, text)

    def test_trailing_digits_are_recovered(self):
        """`1` reads as `l`/`i` more often than not; the snippet must resolve it."""
        for image_path, expected_path in DIGIT_CASES:
            with self.subTest(image=os.path.basename(image_path)):
                got = fix_code(readImage(image_path))
                # every one of these is recoverable from a same-stem sibling
                for name in ("s0", "s1", "s2", "s3", "cnt2", "state_t"):
                    self.assertIn(name, got)
                # and the misspellings must not survive
                for wrong in ("cntl", "cntI", "vall", "vali", "sQ"):
                    self.assertNotIn(wrong, got)
                ratio = difflib.SequenceMatcher(
                    None, _normalise(got), _normalise(_read(expected_path))).ratio()
                self.assertGreaterEqual(ratio, 0.93, f"only {ratio:.1%}\n{got}")

    def test_post_processing_never_makes_digits_worse(self):
        """A correctly read trailing digit must not be voted away."""
        for image_path, _expected in DIGIT_CASES:
            with self.subTest(image=os.path.basename(image_path)):
                raw = readImage(image_path)
                fixed = fix_code(raw)
                for name in ("cnt1", "cnt2", "s1", "s2"):
                    self.assertGreaterEqual(
                        fixed.count(name), raw.count(name),
                        f"{name} got rarer after post-processing")

    def test_blank_lines_between_blocks_are_kept(self):
        text = readImage(os.path.join(DATA, "vhdl_dark.png"))
        self.assertIn("\n\n", text, "vertical gaps were lost")

    def test_no_whitelist_swallows_the_spaces(self):
        # the old config dropped every space, producing `intmain`
        text = readImage(os.path.join(IMAGES, "screenshot_0.png"))
        self.assertIn("int main", text)
        self.assertNotIn("intmain", text)


@unittest.skipUnless(HAS_TESSERACT, "tesseract is not installed")
class TestPreprocessing(unittest.TestCase):
    def test_dark_and_light_themes_both_normalise_to_dark_on_light(self):
        for name in ("vhdl_dark.png", "vhdl_light.png"):
            with self.subTest(image=name):
                gray = to_gray(Image.open(os.path.join(DATA, name)).convert("RGB"))
                histogram = gray.histogram()
                background = max(range(256), key=lambda i: histogram[i])
                self.assertGreater(background, 128,
                                   "background should end up light")

    def test_line_height_is_measured_sanely(self):
        for image_path, _expected, _lang in CASES:
            with self.subTest(image=os.path.basename(image_path)):
                gray = trim_margins(to_gray(Image.open(image_path).convert("RGB")))
                self.assertGreaterEqual(text_line_height(gray), 4)

    def test_accuracy_survives_other_screen_resolutions(self):
        """A fixed scale factor only suits one display; this must not regress."""
        path = os.path.join(DATA, "vhdl_dark.png")
        want = _normalise(_read(os.path.join(DATA, "vhdl_dark.expected.txt")))
        base = Image.open(path).convert("RGB")
        for factor in (0.75, 1.5, 3.0):
            with self.subTest(scale=factor):
                image = base.resize((int(base.width * factor),
                                     int(base.height * factor)), Image.LANCZOS)
                ratio = difflib.SequenceMatcher(
                    None, _normalise(fix_code(readImage(image))), want).ratio()
                self.assertGreaterEqual(ratio, MIN_SIMILARITY)

    def test_preprocess_accepts_a_path_and_an_image(self):
        path = os.path.join(DATA, "vhdl_dark.png")
        self.assertEqual(preprocess(path).size,
                         preprocess(Image.open(path)).size)

    def test_trim_margins_removes_padding(self):
        source = Image.open(os.path.join(DATA, "vhdl_dark.png")).convert("RGB")
        padded = Image.new("RGB", (source.width + 400, source.height + 400),
                           source.getpixel((0, 0)))
        padded.paste(source, (200, 200))
        self.assertLess(trim_margins(to_gray(padded)).width, source.width + 100)


if __name__ == "__main__":
    unittest.main()
