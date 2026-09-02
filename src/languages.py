"""Language definitions used by the OCR post-processing pipeline.

Each language contributes three things:

* a ``vocabulary`` of keywords / standard identifiers, used to repair tokens the
  OCR split or mangled (``std logic vector`` -> ``std_logic_vector``),
* the literal/comment syntax, so identifier repairs never touch strings or prose,
* an indenter, because C indents on braces and VHDL indents on block keywords.
"""

import re

# --------------------------------------------------------------------------- #
#  Vocabularies
# --------------------------------------------------------------------------- #

C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if", "inline",
    "int", "long", "register", "restrict", "return", "short", "signed",
    "sizeof", "static", "struct", "switch", "typedef", "union", "unsigned",
    "void", "volatile", "while",
    # very common library surface, worth knowing for token repair
    "printf", "scanf", "sprintf", "fprintf", "malloc", "calloc", "realloc",
    "free", "memcpy", "memset", "strlen", "strcpy", "strcmp", "strncmp",
    "fopen", "fclose", "fgets", "fputs", "exit", "include", "define", "ifdef",
    "ifndef", "endif", "pragma", "stdio", "stdlib", "string", "stdint",
    "stdbool", "unistd", "NULL", "main", "argc", "argv",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "int8_t", "int16_t", "int32_t", "int64_t", "size_t", "ssize_t",
}

#: VHDL reserved words. Kept separate from the standard-library names below
#: because a reserved word before `(` is syntax, not a call: `is (`, `not (`,
#: `port (` must keep their space, while `rising_edge(clk)` must not.
VHDL_RESERVED = {
    "abs", "access", "after", "alias", "all", "and", "architecture", "array",
    "assert", "attribute", "begin", "block", "body", "buffer", "bus", "case",
    "component", "configuration", "constant", "disconnect", "downto", "else",
    "elsif", "end", "entity", "exit", "file", "for", "function", "generate",
    "generic", "group", "guarded", "if", "impure", "in", "inertial", "inout",
    "is", "label", "library", "linkage", "literal", "loop", "map", "mod",
    "nand", "new", "next", "nor", "not", "null", "of", "on", "open", "or",
    "others", "out", "package", "port", "postponed", "procedure", "process",
    "pure", "range", "record", "register", "reject", "rem", "report", "return",
    "rol", "ror", "select", "severity", "signal", "shared", "sla", "sll",
    "sra", "srl", "subtype", "then", "to", "transport", "type", "unaffected",
    "units", "until", "use", "variable", "wait", "when", "while", "with",
    "xnor", "xor",
}

#: Standard types / libraries / functions. These carry the underscores that OCR
#: most often loses, so they matter for token repair.
VHDL_STANDARD = {
    "std_logic", "std_logic_vector", "std_ulogic", "std_ulogic_vector",
    "std_logic_1164", "std_logic_arith", "std_logic_unsigned",
    "std_logic_signed", "std_logic_textio", "numeric_std", "numeric_bit",
    "math_real", "textio", "ieee", "work", "std",
    "bit", "bit_vector", "boolean", "character", "integer", "natural",
    "positive", "real", "severity_level", "signed", "string", "time",
    "unsigned",
    "rising_edge", "falling_edge", "to_integer", "to_unsigned", "to_signed",
    "to_stdlogicvector", "to_std_logic_vector", "conv_integer",
    "conv_std_logic_vector", "resize", "shift_left", "shift_right",
    "clk", "reset", "reset_n", "clock", "enable", "data_in", "data_out",
    "write_enable", "read_enable", "chip_select", "output_enable",
    "rtl", "behavioral", "behaviour", "structural",
}

VHDL_KEYWORDS = VHDL_RESERVED | VHDL_STANDARD

#: Legal ``std_logic`` character-literal values; used to repair ``'@'`` -> ``'0'``.
VHDL_LOGIC_VALUES = set("UX01ZWLH-")

#: OCR misreadings of the nine legal std_logic values.
VHDL_LOGIC_CONFUSIONS = {
    "@": "0", "O": "0", "o": "0", "Q": "0", "D": "0", "()": "0",
    "l": "1", "I": "1", "|": "1", "i": "1", "!": "1",
    "z": "Z", "w": "W", "x": "X", "u": "U", "h": "H",
    "~": "-", "_": "-", "—": "-", "–": "-",
}


# --------------------------------------------------------------------------- #
#  Indenters
# --------------------------------------------------------------------------- #

def indent_c(lines, unit="    "):
    """Brace-driven indentation."""
    out, depth = [], 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        # a line that starts by closing a block sits one level out
        here = depth - 1 if stripped.startswith("}") else depth
        # preprocessor directives always live at column 0
        prefix = "" if stripped.startswith("#") else unit * max(here, 0)
        out.append(prefix + stripped)
        depth = max(0, depth + stripped.count("{") - stripped.count("}"))
    return out


#: A VHDL block opener and the kind of block it starts. `process`, `block` and
#: the generate forms may carry a `label :` prefix, which is why the optional
#: group is there -- `P1: process(Clk)` is by far the common way to write one.
_LABEL = r"(?:\w+[ \t]*:[ \t]*)?"
_VHDL_OPENERS = tuple(
    (re.compile("^" + pattern, re.I), kind) for pattern, kind in (
        (_LABEL + r"(?:if|for)\b.*\bgenerate[ \t]*$", "generate"),
        (_LABEL + r"process\b", "process"),
        (_LABEL + r"block\b", "block"),
        (r"entity\b.*\bis\b", "entity"),
        (r"architecture\b.*\bis\b", "architecture"),
        (r"package\b.*\bis\b", "package"),
        (r"configuration\b.*\bis\b", "configuration"),
        (r"component\b", "component"),
        (r"(?:function|procedure)\b.*\bis[ \t]*$", "subprogram"),
        (r"generic[ \t]*\(", "paren"),
        (r"port[ \t]*\(", "paren"),
        (r"if\b.*\bthen[ \t]*$", "if"),
        (r"case\b.*\bis[ \t]*$", "case"),
        (r"(?:for|while)\b.*\bloop[ \t]*$", "loop"),
        (r"loop[ \t]*$", "loop"),
        (r"record[ \t]*$", "record"),
    )
)

#: Block kinds that `end <kind>;` names explicitly.
_VHDL_BLOCK_KINDS = {
    "if", "case", "loop", "process", "architecture", "entity", "component",
    "package", "record", "generate", "block", "procedure", "function",
    "configuration", "units", "subprogram",
}

_VHDL_END = re.compile(r"^end\b[ \t]*(\w+)?", re.I)
_VHDL_CLOSE_PAREN = re.compile(r"^\)[ \t]*;?[ \t]*$")
_VHDL_MID_BLOCK = re.compile(r"^(begin|else|elsif)\b", re.I)
#: ``when x =>`` with its statements on following lines opens an alternative;
#: ``when x => y <= a;`` fits on one line and opens nothing.
_VHDL_WHEN_BLOCK = re.compile(r"^when\b.*=>[ \t]*$", re.I)


def _opener_kind(line):
    for pattern, kind in _VHDL_OPENERS:
        if pattern.match(line):
            return kind
    return None


def _close_block(stack, kind):
    """Pop back to the named block, discarding anything left unclosed inside it.

    This is what stops one dropped `end if;` from cascading: `end process P1;`
    unwinds to the process no matter how many `if`s the OCR lost along the way.
    """
    if kind in _VHDL_BLOCK_KINDS and kind in stack:
        while stack and stack.pop() != kind:
            pass
    elif stack:
        stack.pop()


def indent_vhdl(lines, unit="    "):
    """Indent by tracking open blocks on a stack.

    A stack rather than a counter, so that `end <kind>;` lands at the level of
    the block it names even when the OCR dropped an inner `end if;`.
    """
    out, stack = [], []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue

        end = _VHDL_END.match(stripped)
        if end:
            kind = (end.group(1) or "").lower()
            if kind == "case":              # the last alternative closes with it
                while stack and stack[-1] == "when":
                    stack.pop()
            _close_block(stack, kind)
            out.append(unit * len(stack) + stripped)
        elif _VHDL_CLOSE_PAREN.match(stripped):
            if stack and stack[-1] == "paren":
                stack.pop()
            out.append(unit * len(stack) + stripped)
        elif _VHDL_WHEN_BLOCK.match(stripped):
            if stack and stack[-1] == "when":
                stack.pop()               # close the previous alternative
            out.append(unit * len(stack) + stripped)
            stack.append("when")
        elif _VHDL_MID_BLOCK.match(stripped):
            # `begin`/`else`/`elsif` sit one level out but keep the block open
            out.append(unit * max(len(stack) - 1, 0) + stripped)
        else:
            out.append(unit * len(stack) + stripped)
            kind = _opener_kind(stripped)
            if kind:
                stack.append(kind)
    return out


# --------------------------------------------------------------------------- #
#  Language records
# --------------------------------------------------------------------------- #

class Language:
    def __init__(self, key, label, extension, vocabulary,
                 line_comment, block_comment, indenter, detect):
        self.key = key
        self.label = label
        self.extension = extension
        self.vocabulary = {w.lower() for w in vocabulary}
        self.line_comment = line_comment
        self.block_comment = block_comment
        self.indenter = indenter
        self._detect = detect

    def score(self, text):
        """How strongly `text` looks like this language (higher wins)."""
        return sum(weight * len(pattern.findall(text))
                   for pattern, weight in self._detect)

    def __repr__(self):
        return f"<Language {self.key}>"


def _pats(*pairs):
    return [(re.compile(p, re.I | re.M), w) for p, w in pairs]


C = Language(
    key="c",
    label="C / C++",
    extension=".c",
    vocabulary=C_KEYWORDS,
    line_comment="//",
    block_comment=("/*", "*/"),
    indenter=indent_c,
    detect=_pats(
        (r"^\s*#\s*(include|define|ifndef|pragma)\b", 6),
        (r"\bprintf\s*\(", 4),
        (r"\b(int|void|char|float|double)\s+\w+\s*\(", 3),
        (r"\bstruct\b", 2),
        (r"->", 1),
        (r"[{}]", 1),
        (r";\s*$", 1),
        (r"\bmalloc\b|\bfree\b|\bsizeof\b", 3),
        (r"\breturn\b", 1),
    ),
)

VHDL = Language(
    key="vhdl",
    label="VHDL",
    extension=".vhd",
    vocabulary=VHDL_KEYWORDS,
    line_comment="--",
    block_comment=None,
    indenter=indent_vhdl,
    detect=_pats(
        (r"\barchitecture\b", 8),
        (r"\bentity\b", 8),
        (r"\bstd_logic\b|std[ _]?logic[ _]?vector", 6),
        (r"^\s*library\s+\w+\s*;", 6),
        (r"\bport\s*\(|\bgeneric\s*\(", 5),
        (r"\bdownto\b|\bupto\b", 5),
        (r"\bend\s+(process|if|case|loop|architecture|entity|component)\b", 5),
        (r"\bprocess\s*\(", 4),
        (r"\bsignal\b|\bvariable\b", 3),
        (r"<=", 2),
        (r":=", 2),
        (r"\bothers\s*=>", 3),
        (r"^\s*--", 2),
    ),
)

LANGUAGES = {lang.key: lang for lang in (C, VHDL)}
DEFAULT = C


def get(key):
    """Look up a language by key; unknown keys fall back to C."""
    return LANGUAGES.get((key or "").lower(), DEFAULT)


def detect(text, default=DEFAULT):
    """Guess the language of an OCR'd snippet."""
    if not text or not text.strip():
        return default
    scores = {lang: lang.score(text) for lang in LANGUAGES.values()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else default
