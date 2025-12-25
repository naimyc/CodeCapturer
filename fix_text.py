import re

def fix_c_ocr(text: str) -> str:
    # ---------- einfache OCR-Fixes ----------
    fixes = {
            " ;": ";",
            " ,": ",",
            " (": "(",
            ") ": ")",
            "{ ": "{",
            " }": "}",
            "[ ": "[",
            " ]": "]",
            "| |": "||",
            "& &": "&&",
            "= =": "==",
            "! =": "!=",
            "< =": "<=",
            "> =": ">=",
            "&1i": "&i",
            "stdl1o.n": "stdio.h",
            # "intergebnis": "int ergebnis",
            # "inti": "int i",
            # "intmain": "int main",
            "arrayl": "array1",
            "return(": "return (",
            "Sarray11": "&array1",
            "Garray": "&array",
            "S&array": "&array",
            "S&array": "&array",
            "Sarray": "&array",
            "Sarray": "&array",
            "S&array" : "&array",
            "S&arrayO": "&array0",
            "arrayO": "array0",
            "arrayd": "array0",
            "22[": "z2["
    }

    for k, v in fixes.items():
        text = text.replace(k, v)
        
    # ---------- space after type keywords ----------
    text = re.sub(r"\b(int|float|double|char|void|struct|sizeof)([A-Za-z_])", r"\1 \2", text)

    # ---------- fehlende Leerzeichen ----------
    text = re.sub(r"\bint([a-zA-Z_])", r"int \1", text)
    text = re.sub(r"\breturn\(", "return (", text)

    # ---------- Funktionsdeklarationen ----------
    text = re.sub(r"\bintadd\b", "int add", text)
    text = re.sub(r"\bintmul\b", "int mul", text)
    text = re.sub(r"\bintmul\b", "int mul", text)
    text = re.sub(r"\bvoidadd\b", "void add", text)
    text = re.sub(r"\bintmain\b", "int main", text)
    text = re.sub(r"\bfloatsub\b", "float sub", text)
    
    # Fix misplaced brackets and OCR errors
    # Replace things like "9]" with "[9]"
    # text = re.sub(r"(\d+)\]", r"[\1]", text)
    text = re.sub(r"([a-zA-Z]+)\(\s*(\d+)\s*\]", r"\1[\2]", text)
    text = re.sub(r"([a-zA-Z_]\w*)\(\s*(\d+)\s*\]", r"\1[\2]", text)

    # ---------- Pointer spacing ----------
    text = re.sub(r"\*(\w)", r"* \1", text)
    text = re.sub(r"(\w)\*", r"\1 *", text)

    # ---------- printf Fix ----------
    text = re.sub(r'printf\("%s*d"', 'printf("%d"', text)
    text = re.sub(r'printf\("%si"', 'printf("%i"', text)

    # ---------- doppelte Leerzeichen ----------
    text = re.sub(r"[ \t]+", " ", text)

    # ---------- saubere Einrückung ----------
    lines = []
    indent = 0
    for line in text.splitlines():
        line = line.strip()
        if line.endswith("}"):
            indent -= 1
        lines.append("    " * max(indent, 0) + line)
        if line.endswith("{"):
            indent += 1

    return "\n".join(lines)
