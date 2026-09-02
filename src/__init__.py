"""CodeCapturer: screenshot -> source code."""

from .fix_text import detect_language, fix_c_ocr, fix_code
from .reader import readImage, readTextFromImage

__all__ = [
    "readImage",
    "readTextFromImage",
    "fix_code",
    "fix_c_ocr",
    "detect_language",
]
