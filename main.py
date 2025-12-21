import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # ⭐ DPI FIX

import tkinter as tk
from PIL import ImageGrab
import pytesseract

class ScreenCapture:
    def __init__(self):
        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(background='gray')

        self.start_x = self.start_y = 0
        self.rect = None

        self.canvas = tk.Canvas(self.root, cursor="cross", bg="gray")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)

        self.root.mainloop()

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y

        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y,
            self.start_x, self.start_y,
            outline='red', width=2
        )

    def on_move(self, event):
        self.canvas.coords(
            self.rect,
            self.start_x, self.start_y,
            event.x, event.y
        )

    def on_button_release(self, event):
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)

        # Convert to screen coordinates
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()

        bbox = (
            x1 + root_x,
            y1 + root_y,
            x2 + root_x,
            y2 + root_y
        )

        # Hide overlay before capture
        self.root.withdraw()
        self.root.update()

        img = ImageGrab.grab(bbox=bbox)
        img.save("screenshot.png")

        # text = pytesseract.image_to_string(img)
        # print("OCR Result:\n", text)

        self.root.destroy()

if __name__ == "__main__":
    ScreenCapture()
