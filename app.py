import ctypes
import os
import sys

# Must run before the viewport is created. Without it Windows reports a logical
# client size on a scaled display, so the panes only paint part of the window.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
except (AttributeError, OSError):
    pass

import dearpygui.dearpygui as dpg
from PIL import Image, ImageGrab

from src import languages
from src.fix_text import detect_language, fix_code
from src.reader import readImage

dpg.create_context()

# ------------------------- Global Variables -------------------------
current_texture = None
original_image = None   # full-resolution image, the one OCR actually reads
source_image = None     # the untouched load, so "Reset" can undo a crop
preview_rect = None

#: Dropdown label -> language key passed to fix_code()
LANGUAGE_CHOICES = {"Auto-detect": "auto"}
LANGUAGE_CHOICES.update({lang.label: lang.key for lang in languages.LANGUAGES.values()})

#: Where the trim marker starts on a freshly loaded image. Screenshots usually
#: clip a sliver of the previous column, and that sliver is the biggest source
#: of OCR junk, so the marker is pre-positioned past it.
DEFAULT_TRIM = 25

# ------------------------- UI scaling --------------------------------
#: Viewport the widget sizes below were chosen for; scaling is relative to it.
BASE_WIDTH, BASE_HEIGHT = 1020, 700
BASE_FONT_SIZE = 15
MIN_UI_SCALE, MAX_UI_SCALE = 1.0, 2.4

#: Font sizes built up front. Rebuilding a font atlas on every resize is far too
#: slow, so a ladder is baked once and the nearest rung is bound on the fly.
FONT_SIZES = (13, 15, 17, 19, 21, 24, 27, 30, 33, 36)

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)

#: How far a small image may be blown up to fill the pane before it just looks
#: soft rather than bigger.
MAX_IMAGE_UPSCALE = 4.0

#: Widget tag -> width at scale 1.0. 260 is what the longest button label needs.
SCALED_WIDTHS = {
    "btn_select": 260, "btn_paste": 260, "btn_ocr": 260,
    "crop_x1": 150, "btn_crop": 125, "btn_reset": 125,
    "language_choice": 165, "btn_save": 100,
}

#: Buttons get a scaled height too; the rest size themselves off the font.
BASE_BUTTON_HEIGHT = 34
BUTTONS = ("btn_select", "btn_paste", "btn_ocr",
           "btn_crop", "btn_reset", "btn_save")

_fonts = {}


def build_fonts():
    """Bake one font per size in the ladder. Must run before the viewport starts."""
    path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
    if not path:
        return
    with dpg.font_registry():
        for size in FONT_SIZES:
            _fonts[size] = dpg.add_font(path, size)


def ui_scale():
    """How much bigger than the base layout the viewport currently is."""
    width = dpg.get_viewport_client_width()
    height = dpg.get_viewport_client_height()
    if width < 2 or height < 2:
        return 1.0
    scale = min(width / BASE_WIDTH, height / BASE_HEIGHT)
    return max(MIN_UI_SCALE, min(MAX_UI_SCALE, scale))


def apply_ui_scale(scale):
    """Grow the type and the controls to match the window."""
    if _fonts:
        wanted = BASE_FONT_SIZE * scale
        nearest = min(_fonts, key=lambda size: abs(size - wanted))
        dpg.bind_font(_fonts[nearest])
    elif hasattr(dpg, "set_global_font_scale"):
        dpg.set_global_font_scale(scale)          # no TTF found; blurrier fallback

    for tag, base in SCALED_WIDTHS.items():
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, width=int(base * scale))

    for tag in BUTTONS:
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, height=int(BASE_BUTTON_HEIGHT * scale))


def set_status(message):
    dpg.set_value("status_text", message)


# ------------------------- GUI Functions -----------------------------
def displayed_size():
    """Size the image is drawn at, which is what the crop rectangle is in."""
    return (dpg.get_item_width("image_display") or 0,
            dpg.get_item_height("image_display") or 0)


def container_size():
    """Rendered size of the image pane, which grows with the window."""
    size = dpg.get_item_rect_size("image_display_container")
    if size and size[0] > 1 and size[1] > 1:
        return int(size[0]), int(size[1])
    return 800, 600


def refresh_image_soon(delay=3):
    """Re-fit the image once the new layout has actually been laid out.

    A child window only reports its new rect after DearPyGui has drawn a frame
    at the new size, so fitting the image during the resize callback measures
    the *old* pane and leaves the image too small.
    """
    if original_image is None:
        return
    try:
        dpg.set_frame_callback(dpg.get_frame_count() + delay,
                               lambda *_: update_image_widget())
    except Exception:
        update_image_widget()


def update_image_widget():
    """Update the displayed image texture"""
    global current_texture, original_image

    if original_image is None:
        return

    window_width, window_height = container_size()
    available_width = max(window_width - 24, 64)
    available_height = max(window_height - 24, 64)

    # `thumbnail` only ever shrinks, which left a small screenshot tiny in a big
    # pane. Scale to fill instead, capped so a postage stamp is not blown up
    # into a blurry wall.
    source_width, source_height = original_image.size
    fit = min(available_width / source_width, available_height / source_height,
              MAX_IMAGE_UPSCALE)
    width = max(1, round(source_width * fit))
    height = max(1, round(source_height * fit))

    img = original_image.resize((width, height), Image.LANCZOS)

    pixels = [c / 255 for px in img.getdata() for c in px]  # RGBA normalized

    if current_texture:
        dpg.delete_item(current_texture)

    with dpg.texture_registry():
        current_texture = dpg.add_dynamic_texture(width, height, pixels)

    dpg.configure_item("image_display", texture_tag=current_texture,
                       width=width, height=height)
    dpg.configure_item("crop_x1", max_value=max(width - 1, 0))
    update_preview_rectangle()


def crop_image(p1, p2):
    """Crop the original image using coordinates in displayed image space"""
    global original_image
    if original_image is None:
        return

    disp_width, disp_height = displayed_size()
    if disp_width <= 0 or disp_height <= 0:
        return

    orig_width, orig_height = original_image.size
    scale_x = orig_width / disp_width
    scale_y = orig_height / disp_height

    left = int(min(p1[0], p2[0]) * scale_x)
    upper = int(min(p1[1], p2[1]) * scale_y)
    right = int(max(p1[0], p2[0]) * scale_x)
    lower = int(max(p1[1], p2[1]) * scale_y)

    left = max(0, min(left, orig_width))
    upper = max(0, min(upper, orig_height))
    right = max(0, min(right, orig_width))
    lower = max(0, min(lower, orig_height))

    if right - left < 2 or lower - upper < 2:
        set_status("Crop region is too small.")
        return

    original_image = original_image.crop((left, upper, right, lower))
    update_image_widget()
    set_status(f"Cropped to {original_image.width}x{original_image.height}.")


def manual_crop():
    """Trim everything left of the X1 marker.

    Screenshots often clip a sliver of the previous column, and that sliver is
    the single biggest source of OCR junk, so cutting it off is worth a button.
    """
    x1 = dpg.get_value("crop_x1")
    width, height = displayed_size()
    crop_image((x1, 0), (width, height))


def reset_image():
    global original_image
    if source_image is None:
        return
    original_image = source_image.copy()
    update_image_widget()
    dpg.set_value("crop_x1", DEFAULT_TRIM)
    update_preview_rectangle()
    set_status("Reset to the original image.")


def load_image(path_or_image, label):
    """Load image and initialize input values"""
    global original_image, source_image
    if isinstance(path_or_image, Image.Image):
        source_image = path_or_image.convert("RGBA")
    else:
        source_image = Image.open(path_or_image).convert("RGBA")
    original_image = source_image.copy()

    # size the widget first so the slider's max is known, then place the marker
    update_image_widget()
    refresh_image_soon()
    dpg.set_value("crop_x1", DEFAULT_TRIM)
    update_preview_rectangle()
    set_status(f"Loaded {label} ({source_image.width}x{source_image.height}) - "
               f"trim marker at {dpg.get_value('crop_x1')}px.")


def selected_language():
    return LANGUAGE_CHOICES.get(dpg.get_value("language_choice"), "auto")


def run_ocr():
    """Run OCR on the current image"""
    if original_image is None:
        set_status("Load or paste an image first.")
        return

    set_status("Reading...")
    try:
        raw = readImage(original_image.convert("RGB"))
    except Exception as error:                       # tesseract missing, etc.
        set_status(f"OCR failed: {error}")
        return

    language = selected_language()
    text = fix_code(raw, lang=language, reindent=dpg.get_value("reindent"))
    dpg.set_value("code_editor", text)

    detected = detect_language(raw)
    shown = languages.get(detected).label
    if language == "auto":
        set_status(f"Done - detected {shown}.")
    else:
        set_status(f"Done - read as {languages.get(language).label}.")


def save_code(sender=None, app_data=None):
    """Write the editor contents next to the other captures."""
    text = dpg.get_value("code_editor")
    if not text.strip():
        set_status("Nothing to save.")
        return

    key = selected_language()
    if key == "auto":
        key = detect_language(text)
    extension = languages.get(key).extension

    folder = "c_files"
    os.makedirs(folder, exist_ok=True)
    index = len(os.listdir(folder))
    path = os.path.join(folder, f"capture_{index}{extension}")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    set_status(f"Saved to {path}")


# ------------------------- Preview Rectangle -------------------------
def update_preview_rectangle():
    """Draw or update the crop marker on the image"""
    global preview_rect
    if original_image is None:
        return

    x1 = dpg.get_value("crop_x1")
    width, height = displayed_size()

    if preview_rect is None:
        preview_rect = dpg.draw_rectangle((x1, 0), (width, height),
                                          color=(255, 0, 0, 255),
                                          thickness=2,
                                          parent="draw_layer")
    else:
        dpg.configure_item(preview_rect, pmin=(x1, 0), pmax=(width, height))


# ------------------------- File & Clipboard -------------------------
def file_selected(sender, app_data):
    selections = app_data["selections"]
    for name, file in selections.items():
        load_image(file, name)
        break


def paste_image():
    img = ImageGrab.grabclipboard()
    if isinstance(img, Image.Image):
        load_image(img, "clipboard")
    else:
        set_status("No image on the clipboard.")


# ------------------------- GUI Setup --------------------------------
build_fonts()   # before the viewport starts, so the atlas is baked once

with dpg.file_dialog(directory_selector=False, show=False, callback=file_selected,
                     tag="file_dialog", width=600, height=400):
    dpg.add_file_extension(".*")
    dpg.add_file_extension(".png")
    dpg.add_file_extension(".jpg")
    dpg.add_file_extension(".jpeg")

# Left: Image viewer
with dpg.window(label="Image Viewer", width=500, height=650, tag="main_window"):
    with dpg.group(horizontal=True):
        with dpg.group(horizontal=False):
            dpg.add_button(label="Select Image", tag="btn_select", width=185,
                           callback=lambda: dpg.show_item("file_dialog"))
            dpg.add_button(label="Paste from Clipboard", tag="btn_paste", width=185,
                           callback=paste_image)
            dpg.add_button(label="Convert Image to Text (OCR)", tag="btn_ocr",
                           width=185, callback=run_ocr)

        # ------------------ Manual Crop Controls ------------------
        with dpg.group(horizontal=False):
            dpg.add_text("Trim left edge")
            dpg.add_slider_int(tag="crop_x1", label="X1", width=120,
                               default_value=DEFAULT_TRIM, min_value=0,
                               max_value=500,
                               callback=lambda s, a: update_preview_rectangle())
            with dpg.group(horizontal=True):
                dpg.add_button(label="Crop", tag="btn_crop",
                               callback=manual_crop, width=90)
                dpg.add_button(label="Reset", tag="btn_reset",
                               callback=reset_image, width=90)

    with dpg.group(horizontal=True):
        dpg.add_text("Language")
        dpg.add_combo(list(LANGUAGE_CHOICES), tag="language_choice",
                      default_value="Auto-detect", width=140)
        dpg.add_checkbox(label="Re-indent", tag="reindent", default_value=True)

    dpg.add_separator()

    # ------------------ Image Display ------------------
    with dpg.child_window(tag="image_display_container", autosize_x=True,
                          autosize_y=True):
        with dpg.texture_registry():
            empty_texture = dpg.add_dynamic_texture(1, 1, [0, 0, 0, 0])
        dpg.add_image(empty_texture, tag="image_display")
        dpg.add_drawlist(width=-1, height=-1, tag="draw_layer")

with dpg.window(label="Code Viewer / Editor", width=500, height=650,
                tag="code_window", pos=(510, 0)):
    with dpg.group(horizontal=True):
        dpg.add_text("Extracted Code / OCR Output")
        dpg.add_button(label="Save", tag="btn_save", callback=save_code, width=80)
    dpg.add_text("Load an image, then press OCR.", tag="status_text", wrap=480)
    # height=-1 lets the editor take whatever is left after the two rows above
    dpg.add_input_text(multiline=True, height=-1, width=-1,
                       default_value="", tag="code_editor")


# ------------------------- Layout ----------------------------------
def layout_windows():
    """Tile the two panes across the viewport and scale the UI to match."""
    width = dpg.get_viewport_client_width()
    height = dpg.get_viewport_client_height()
    if width < 2 or height < 2:
        return

    apply_ui_scale(ui_scale())

    left = width // 2
    dpg.configure_item("main_window", pos=(0, 0), width=left, height=height)
    dpg.configure_item("code_window", pos=(left, 0),
                       width=width - left, height=height)
    dpg.configure_item("status_text", wrap=max(width - left - 30, 100))


def viewport_resize(sender=None, app_data=None):
    layout_windows()
    update_image_widget()
    refresh_image_soon()   # again once the panes report their new size


dpg.set_viewport_resize_callback(viewport_resize)

# ------------------------- Start GUI -------------------------------
dpg.create_viewport(title="CodeCapturer", width=1020, height=700)
dpg.setup_dearpygui()
dpg.show_viewport()
layout_windows()

# `python app.py shot.png` opens straight onto an image
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    load_image(sys.argv[1], os.path.basename(sys.argv[1]))

dpg.start_dearpygui()
dpg.destroy_context()
