import dearpygui.dearpygui as dpg
from PIL import Image, ImageGrab, ImageOps
import pytesseract
from time import sleep
from src.reader import readImage

dpg.create_context()

# ------------------------- Global Variables -------------------------
current_texture = None
original_image = None       # Original image
crop_rect = None            # Crop rectangle (x1, y1, x2, y2)
drag_start = None           # Mouse down position
preview_rect = None         # Rectangle item for preview

# ------------------------- OCR Function -----------------------------
def read_text_from_image(img: "PIL.Image"):
    if img.width == 0 or img.height == 0:
        return "# Error: image has zero width or height"
    
    # Upscale
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img)
    # Tesseract config
    config = (
        "--psm 6 "
        "-c preserve_interword_spaces=1 "
        "-c tessedit_enable_dict_correction=0 "
        "-c tessedit_enable_bigram_correction=0 "
        "-c tessedit_char_whitelist="
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789"
        "_{}[]()<>;=+-*/%!&|^~.,:#\"'\\"
    )
    return pytesseract.image_to_string(img, lang="eng", config=config)

# ------------------------- GUI Functions -----------------------------
def load_image(path):
    global original_image
    original_image = Image.open(path).convert("RGBA")
    update_image_widget()

def update_image_widget():
    global current_texture, original_image

    if original_image is None:
        return

    # Container size
    window_width = dpg.get_item_width("image_display_container") or 800
    window_height = dpg.get_item_height("image_display_container") or 600

    img = original_image.copy()
    img.thumbnail((window_width, window_height))
    width, height = img.size
    if width == 0 or height == 0:
        return

    pixels = [c/255 for px in img.getdata() for c in px]

    if current_texture:
        dpg.delete_item(current_texture)

    with dpg.texture_registry():
        current_texture = dpg.add_dynamic_texture(width, height, pixels)

    dpg.configure_item("image_display", texture_tag=current_texture, width=width, height=height)

# Crop image and OCR
def crop_image():
    global original_image, crop_rect
    if original_image and crop_rect:
        x1, y1, x2, y2 = crop_rect
        # Clamp to image dimensions
        disp_width = dpg.get_item_width("image_display")
        disp_height = dpg.get_item_height("image_display")
        x1 = max(0, min(x1, disp_width))
        x2 = max(0, min(x2, disp_width))
        y1 = max(0, min(y1, disp_height))
        y2 = max(0, min(y2, disp_height))
        if x1 == x2 or y1 == y2:
            return  # invalid crop, skip

        # Scale to original image
        orig_width, orig_height = original_image.size
        scale_x = orig_width / disp_width
        scale_y = orig_height / disp_height

        left = int(min(x1, x2) * scale_x)
        upper = int(min(y1, y2) * scale_y)
        right = int(max(x1, x2) * scale_x)
        lower = int(max(y1, y2) * scale_y)

        left = max(0, min(left, orig_width))
        upper = max(0, min(upper, orig_height))
        right = max(0, min(right, orig_width))
        lower = max(0, min(lower, orig_height))

        cropped = original_image.crop((left, upper, right, lower))
        original_image = cropped
        update_image_widget()
# ------------------------- Mouse Handlers ---------------------------
def mouse_down_handler(sender, app_data):
    global drag_start, preview_rect
    drag_start = dpg.get_mouse_pos()  # get actual (x, y)
    if preview_rect:
        dpg.delete_item(preview_rect)
        preview_rect = None
    preview_rect = dpg.draw_rectangle(drag_start, drag_start, color=(255,0,0,200),
                                      thickness=2, parent="draw_layer")

def mouse_drag_handler(sender, app_data):
    global preview_rect
    if preview_rect:
        preview_rect_end = dpg.get_mouse_pos()
        dpg.configure_item(preview_rect, pmax=preview_rect_end)

def mouse_release_handler(sender, app_data):
    global crop_rect, drag_start, preview_rect
    crop_end = dpg.get_mouse_pos()
    crop_rect = (*drag_start, *crop_end)
    crop_image()
    if preview_rect:
        dpg.delete_item(preview_rect)
        preview_rect = None
    drag_start = None

# Button to manually run OCR
def run_ocr():
    global original_image
    if original_image:
        text = readImage(original_image)
        dpg.set_value("code_editor", text)



# ------------------------- File & Clipboard -------------------------
def file_selected(sender, app_data):
    selections = app_data["selections"]
    for file in selections.values():
        load_image(file)
        break

def paste_image():
    img = ImageGrab.grabclipboard()
    if isinstance(img, Image.Image):
        path = "_clipboard.png"
        img.save(path)
        load_image(path)

# ------------------------- GUI Setup --------------------------------
with dpg.file_dialog(directory_selector=False, show=False, callback=file_selected, tag="file_dialog"):
    dpg.add_file_extension(".*")
    dpg.add_file_extension(".png")
    dpg.add_file_extension(".jpg")
    dpg.add_file_extension(".jpeg")

# Main Image Window
with dpg.window(label="Image Viewer", width=500, height=650, tag="main_window"):
    dpg.add_text("Select or Paste an Image")
    dpg.add_button(label="Select Image", callback=lambda: dpg.show_item("file_dialog"))
    dpg.add_button(label="Paste from Clipboard", callback=paste_image)
    dpg.add_separator()
    dpg.add_button(label="Convert Image to Text (OCR)", callback=run_ocr)

    # Child window for image
    with dpg.child_window(tag="image_display_container", autosize_x=True, autosize_y=True):
        with dpg.texture_registry():
            empty_texture = dpg.add_dynamic_texture(1, 1, [0,0,0,0])
        dpg.add_image(empty_texture, tag="image_display")

        # Drawlist for preview rectangle
        dpg.drawlist(width=-1, height=-1, tag="draw_layer")

        # Handler registry for mouse drag
        with dpg.handler_registry():
            dpg.add_mouse_down_handler(callback=mouse_down_handler)
            dpg.add_mouse_drag_handler(callback=mouse_drag_handler)
            dpg.add_mouse_release_handler(callback=mouse_release_handler)

# Code Viewer / Editor Window
with dpg.window(label="Code Viewer / Editor", width=500, height=650, tag="code_window", pos=(510,0)):
    dpg.add_text("Extracted Code / OCR Output")
    dpg.add_input_text(multiline=True, height=600, width=-1, default_value="# OCR Output Here", tag="code_editor")

# Viewport resize callback
def viewport_resize(sender, app_data):
    update_image_widget()

dpg.set_viewport_resize_callback(viewport_resize)

# ------------------------- Start GUI -------------------------------
dpg.create_viewport(title="Image + OCR Viewer", width=1020, height=700)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()