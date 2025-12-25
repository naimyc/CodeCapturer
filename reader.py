from PIL import ImageGrab, ImageOps, Image
import pytesseract
from time import sleep


def readImage(bbox):
    # ---------- Screenshot ----------
        img = ImageGrab.grab(bbox=bbox)
        img.save("screenshot.png")
        

        # Upscale (sehr wichtig)
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        # Graustufen + Kontrast
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img)

        # ---------- Tesseract ----------
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

        sleep(0.5)  # Warten, bis das Bild bereit ist

        text = pytesseract.image_to_string(
            img,
            lang="eng",
            config=config
        )
        return text