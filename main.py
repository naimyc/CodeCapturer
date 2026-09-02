"""Drag a box over code on screen; the selection is OCR'd and written to disk."""

import argparse
import ctypes
import os
import tkinter as tk

from src import languages
from src.fix_text import detect_language, fix_code
from src.reader import readImage

ctypes.windll.shcore.SetProcessDpiAwareness(2)

OUTPUT_DIR = "c_files"


class ScreenCapture:
    def __init__(self, lang="auto", reindent=True):
        self.lang = lang
        self.reindent = reindent
        self.text = None
        self.path = None

        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(background="gray")

        self.start_x = self.start_y = 0
        self.rect = None

        self.canvas = tk.Canvas(self.root, cursor="cross", bg="gray")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<Escape>", lambda event: self.root.destroy())

        self.root.mainloop()

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y,
            self.start_x, self.start_y,
            outline="red", width=2
        )

    def on_move(self, event):
        self.canvas.coords(
            self.rect,
            self.start_x, self.start_y,
            event.x, event.y
        )

    def on_button_release(self, event):
        x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
        x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)

        root_x, root_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        bbox = (x1 + root_x, y1 + root_y, x2 + root_x, y2 + root_y)

        # hide the overlay before grabbing, or we capture our own grey tint
        self.root.withdraw()
        self.root.update()

        if x2 - x1 < 5 or y2 - y1 < 5:
            self.root.destroy()
            return

        # ---------- OCR ----------
        raw = readImage(bbox)
        self.text = fix_code(raw, lang=self.lang, reindent=self.reindent)

        key = self.lang if self.lang != "auto" else detect_language(raw)
        self.path = self.write(self.text, languages.get(key).extension)
        print(self.text)
        print(f"\n-> {self.path}")

        self.root.destroy()

    @staticmethod
    def write(text, extension):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        index = len(os.listdir(OUTPUT_DIR))
        path = os.path.join(OUTPUT_DIR, f"capture_{index}{extension}")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-l", "--lang", default="auto",
                        choices=["auto", *languages.LANGUAGES],
                        help="source language of the captured code")
    parser.add_argument("--no-reindent", action="store_true",
                        help="keep the indentation as read instead of rebuilding it")
    args = parser.parse_args()

    ScreenCapture(lang=args.lang, reindent=not args.no_reindent)


if __name__ == "__main__":
    main()
