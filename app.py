import dearpygui.dearpygui as dpg
from PIL import Image, ImageGrab
from src.reader import readImage
from src.fix_text import fix_c_ocr

dpg.create_context()

# ------------------------- Global Variables -------------------------
current_texture = None
original_image = None  # Original image
preview_rect = None

# ------------------------- GUI Functions -----------------------------
def update_image_widget():
    """Update the displayed image texture"""
    global current_texture, original_image

    if original_image is None:
        return

    window_width = dpg.get_item_width("image_display_container") or 800
    window_height = dpg.get_item_height("image_display_container") or 600

    img = original_image.copy()
    img.thumbnail((window_width, window_height))
    width, height = img.size
    if width == 0 or height == 0:
        return

    pixels = [c / 255 for px in img.getdata() for c in px]  # RGBA normalized

    if current_texture:
        dpg.delete_item(current_texture)

    with dpg.texture_registry():
        current_texture = dpg.add_dynamic_texture(width, height, pixels)

    dpg.configure_item("image_display", texture_tag=current_texture, width=width, height=height)
    update_preview_rectangle()


def crop_image(p1, p2):
    """Crop the original image using coordinates in displayed image space"""
    global original_image
    if original_image is None:
        return

    disp_width = dpg.get_item_width("image_display")
    disp_height = dpg.get_item_height("image_display")
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
        return

    original_image = original_image.crop((left, upper, right, lower))
    update_image_widget()


def manual_crop():
    """Crop the image using input values"""
    x1 = dpg.get_value("crop_x1")
    y1 = 0
    x2 = dpg.get_item_width("image_display_container") or 800
    y2 = dpg.get_item_height("image_display_container") or 600
    crop_image((x1, y1), (x2, y2))


def load_image(path):
    """Load image and initialize input values"""
    global original_image
    original_image = Image.open(path).convert("RGBA")
    # disp_width = dpg.get_item_width("image_display_container") or 800
    # disp_height = dpg.get_item_height("image_display_container") or 600

    # Set default crop inputs to full image size
    dpg.set_value("crop_x1", 25)
    # dpg.set_value("crop_y1", 0)

    update_image_widget()


def run_ocr():
    """Run OCR on the current image"""
    global original_image
    if original_image:
        text = readImage(original_image)
        text = fix_c_ocr(text)
        dpg.set_value("code_editor", text)


# ------------------------- Preview Rectangle -------------------------
def update_preview_rectangle():
    """Draw or update the crop rectangle on the image"""
    global preview_rect
    if original_image is None:
        return

    x1 = dpg.get_value("crop_x1")
    x2 = dpg.get_item_width("image_display_container") or 800
    y1 = 0
    y2 = dpg.get_item_height("image_display_container") or 600

    # Ensure positive coordinates
    x_min, x_max = min(x1, x2), max(x1, x2)
    y_min, y_max = min(y1, y2), max(y1, y2)

    if preview_rect is None:
        preview_rect = dpg.draw_rectangle((x_min, y_min), (x_max, y_max),
                                          color=(255, 0, 0, 255),
                                          thickness=2,
                                          parent="draw_layer")
    else:
        dpg.configure_item(preview_rect, pmin=(x_min, y_min), pmax=(x_max, y_max))


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

# Left: Image viewer
with dpg.window(label="Image Viewer", width=500, height=650, tag="main_window"):
    # ------------------ Image Actions (Keep These) ------------------

    
    with dpg.group(horizontal=True):
        with dpg.group(horizontal=False):
            dpg.add_button(label="Select Image", callback=lambda: dpg.show_item("file_dialog"))
            dpg.add_button(label="Paste from Clipboard", callback=paste_image)
            dpg.add_button(label="Convert Image to Text (OCR)", callback=run_ocr)# Bottom-right: OCR output

        # dpg.add_button(label="Paste from Clipboard", callback=paste_image)
    # ------------------ Manual Crop Controls (Top-Right Overlay) ------------------
        with dpg.group(horizontal=False):  # adjust x for right alignment
            dpg.add_text("Manual Crop ")
            dpg.add_input_int(
                            tag="crop_x1" ,
                            label="X1",
                            width=80,
                            default_value=0,
                            callback=lambda s, a, t="crop_x1": update_preview_rectangle()
                        )
   
            dpg.add_button(label="Crop Image", callback=manual_crop, width=185, )
     # ------------------ Image Display ------------------
    
    dpg.add_separator()
    # dpg.add_button(label="Convert Image to Text (OCR)", callback=run_ocr)# Bottom-right: OCR output
    
    with dpg.child_window(tag="image_display_container", autosize_x=True, autosize_y=True):
        with dpg.texture_registry():
            empty_texture = dpg.add_dynamic_texture(1, 1, [0, 0, 0, 0])
        dpg.add_image(empty_texture, tag="image_display")
        dpg.add_drawlist(width=-1, height=-1, tag="draw_layer")
    
with dpg.window(label="Code Viewer / Editor", width=500, height=650, tag="code_window", pos=(510,0)):
    dpg.add_text("Extracted Code / OCR Output")
    dpg.add_input_text(multiline=True, height=600, width=-1, default_value="# OCR Output Here", tag="code_editor")
# ------------------------- Viewport Resize Callback -----------------
def viewport_resize(sender, app_data):
    update_image_widget()


dpg.set_viewport_resize_callback(viewport_resize)

# ------------------------- Start GUI -------------------------------
dpg.create_viewport(title="Image + OCR Viewer", width=1020, height=700)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()