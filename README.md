# 📸 CodeCapturer

CodeCapturer is a simple and efficient tool that captures code directly from your screen using screenshots and converts it into editable text.

It helps developers, students, and educators quickly extract code from images, PDFs, slides, or videos without manually retyping everything.

---

## 🚀 Features

- 📷 Capture code using screenshots
- 🔍 Extract text from images using OCR
- 💻 Convert extracted text into editable code
- 🧩 **C, VHDL and Python** support, with automatic language detection
- 🔢 Strips the editor's line-number gutter automatically
- 🎨 Handles syntax-highlighted code on light *and* dark themes
- 📐 Keeps blank lines and column alignment; re-indents to canonical style
- 🔍 The two panes tile across the window, and the type and controls scale up
  with it when you maximise
- ⚡ Fast and easy workflow

---

## 🛠️ How It Works

1. Take a screenshot of the code on your screen.
2. The application processes the image.
3. OCR extracts the text from the screenshot.
4. The extracted code is ready to copy and use.

### The OCR pipeline

Editor screenshots break OCR in two specific ways, and each stage exists to undo
one of them:

| Stage | Problem it solves |
| --- | --- |
| Extreme-channel grayscale | Luminance flattens saturated keyword colours toward the background; taking the min (or max, on a dark theme) channel keeps every highlight colour high-contrast. |
| Margin trim + adaptive scaling | Tesseract's LSTM wants roughly 18px of ink per line. A fixed scale factor over- or under-shoots depending on the display, so the factor is derived from the measured line height. |
| Word-box layout rebuild | `image_to_string` discards vertical gaps. Rebuilding from word coordinates keeps blank lines, and snapping the columns to the fitted monospace advance keeps alignment. |
| Vocabulary-driven repair | Underscores are thin and often lost (`std logic vector`). Repairs must be justified by a language keyword or by a token that already appears in the same snippet, so they can't fire on unrelated code. |
| Line-number gutter removal | Screenshots are usually taken with line numbers showing, and OCR reads that column as code. A gutter numbers *every* line and counts up one at a time, which source never does. |
| Per-language indenting | C indents on braces; VHDL on `entity`/`begin`/`if`/`end`. Python's indentation **is** its syntax, so it is preserved as read and never rebuilt. |

**No `tessedit_char_whitelist`.** In LSTM mode a whitelist that omits the space
character makes Tesseract drop *every* space, which is what previously produced
output like `intmain(){`.

Accuracy on the bundled samples (`tests/data`, `c_images`) averages ~99%
character similarity, up from ~71% before this pipeline.

---

## 📦 Installation

Clone the repository:
```
git clone https://github.com/naimyc/CodeCapturer.git
cd CodeCapturer
```

Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) and make
sure `tesseract` is on your `PATH`, then install the Python dependencies:
```
pip install -r requirements.txt
```

Run the GUI (load or paste an image, then press OCR):
```
python app.py                  # start empty
python app.py screenshot.png   # open straight onto an image
```

Or grab a region of the screen directly:
```
python main.py                 # detect the language automatically
python main.py --lang vhdl     # force VHDL (or --lang c / --lang python)
python main.py --no-reindent   # keep the indentation as read
```
Captures are written to `c_files/` with the extension for the detected
language (`.c`, `.vhd` or `.py`).

Run the tests:
```
python -m unittest discover -s tests
```
The OCR tests skip themselves if Tesseract is not installed.

---

## 🧰 Tech Stack

- Python
- Tesseract OCR (via `pytesseract`)
- Pillow for capture and preprocessing
- DearPyGui

---

## 🧩 Adding a language

Languages live in `src/languages.py`. Add a `Language` with its keyword
vocabulary, comment syntax, detection patterns and an indenter, then register it
in `LANGUAGES` — the OCR and repair pipeline picks it up from there.

---

## 🎯 Use Cases

- Extract code from tutorial videos
- Convert code from PDFs into editable text
- Capture shared screen snippets
- Quickly save code examples

---

## ⚠️ Limitations

- Accuracy depends on image quality
- Low resolution or blurry text may reduce accuracy
- Handwritten code is not supported
- A screenshot that clips a sliver of the previous column leaves junk at the
  start of a line; use the **Trim left edge** slider to cut it off before OCR
- Repairs never reach inside a string or comment, since those are prose rather
  than code: a format string read as `"%sd"` stays as it was read
- Tesseract cannot reliably tell `1` from `l`/`i` in a code font, so a trailing
  digit is recovered from the snippet instead: from a numbered sibling (`cnt2`
  proves `cntl` is `cnt1`) or from the same stem coming back two different ways
  (`vall` + `vali` means `val1`). An identifier like `d1` that appears **only**
  as `di`, with no sibling and no second spelling, has no evidence to appeal to
  and stays wrong — set the language explicitly and fix it in the editor pane

---

## 📌 Future Improvements

- Syntax highlighting
- More languages (Verilog, C++)
- Direct IDE integration
- Improved GUI

---

## 🤝 Contributing

Contributions are welcome!

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push and open a Pull Request

---

## 📄 License

This project is licensed under the MIT License.