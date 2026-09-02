"""Repair OCR output so it reads back as source code.

The pipeline is deliberately vocabulary-driven rather than a list of hardcoded
string swaps: every repair has to be justified either by a language keyword or
by a token that already appears elsewhere in the same snippet. That keeps the
fixes from firing on unrelated code.

Order matters:

1. normalise unicode look-alikes (curly quotes, dashes) to ASCII
2. mask strings / character literals / comments so repairs never touch prose
3. repair tokens the OCR split or mangled, using the vocabulary
4. tidy punctuation spacing
5. unmask, then re-indent
"""

import re
from collections import Counter

from . import languages

# --------------------------------------------------------------------------- #
#  1. Unicode normalisation
# --------------------------------------------------------------------------- #

#: Characters Tesseract likes to emit in place of plain ASCII source punctuation.
UNICODE_FIXES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",  # ‘ ’ ‚ ‛
    "´": "'", "`": "'", "°": "'", "ʼ": "'",  # ´ ` ° ʼ
    "“": '"', "”": '"', "„": '"', "‟": '"',  # “ ” „ ‟
    "″": '"', "′": "'",                                # ″ ′
    "–": "-", "—": "-", "―": "-", "−": "-",  # – — ― −
    "…": "...",
    " ": " ", " ": " ", " ": " ",                 # nbsp variants
    "«": "<<", "»": ">>",
    "≤": "<=", "≥": ">=", "≠": "!=",
}

_UNICODE_RE = re.compile("|".join(re.escape(k) for k in UNICODE_FIXES))

#: A doubled quote in front of a one-character literal: ``''0'`` -> ``'0'``.
_DOUBLED_QUOTE_RE = re.compile(r"'{2,}(?=[^'\n]')")


def normalize_unicode(text):
    text = _UNICODE_RE.sub(lambda m: UNICODE_FIXES[m.group()], text)
    return _DOUBLED_QUOTE_RE.sub("'", text)


# --------------------------------------------------------------------------- #
#  2. Literal / comment masking
# --------------------------------------------------------------------------- #

_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile("\x00(\\d+)\x00")


def _segment_re(lang):
    parts = []
    if lang.block_comment:
        open_, close = (re.escape(p) for p in lang.block_comment)
        parts.append(f"{open_}.*?(?:{close}|$)")
    if lang.line_comment:
        parts.append(re.escape(lang.line_comment) + r"[^\n]*")
    parts.append(r'"(?:\\.|[^"\\\n])*"')
    if lang.key == "vhdl":
        parts.append(r"'[^'\n]'")          # character literal, never an attribute tick
    else:
        parts.append(r"'(?:\\.|[^'\\\n])*'")
    return re.compile("|".join(parts), re.S)


def _mask(text, lang):
    """Replace literals/comments with placeholders; return (masked, segments)."""
    segments = []

    def take(match):
        segments.append(match.group())
        return _PLACEHOLDER.format(len(segments) - 1)

    return _segment_re(lang).sub(take, text), segments


def _unmask(text, segments):
    return _PLACEHOLDER_RE.sub(lambda m: segments[int(m.group(1))], text)


# --------------------------------------------------------------------------- #
#  3. Token repair
# --------------------------------------------------------------------------- #

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")

#: Glyph pairs Tesseract genuinely confuses in monospaced code fonts.
CONFUSABLE = {
    "l": "1I|", "1": "lI|", "I": "l1|", "|": "l1I",
    "O": "0QD", "0": "OoQD", "o": "0O", "Q": "0O", "D": "0O",
    "S": "5", "5": "S", "s": "5",
    "B": "8", "8": "B",
    "Z": "2", "2": "Z", "z": "2",
    "g": "9", "9": "gq", "q": "9",
    "G": "6", "6": "Gb", "b": "6",
    "i": "1l",
}

#: Junk glyphs that show up glued to the first token of a line when a screenshot
#: clips the previous column.
_EDGE_JUNK = set("jlLiI|!¦[]{}-_~*")

#: Leading junk left behind when a screenshot clips the previous column: stray
#: punctuation before code, a lone glyph before a comment, or a glyph glued onto
#: a line that is nothing but a closing bracket.
_EDGE_LINE_RE = re.compile(
    r"^(?:[|¦!\]\[.,:;~+]|-(?!-))[ \t]+"
    r"|^[0-9ijlI][ \t]+(?=\x00\d+\x00)"
    r"|^[^\sA-Za-z0-9_ijlI][ \t]*(?=[}\])][ \t]*;?[ \t]*$)"
    r"|^[ijlI1|][ \t]*(?=[}\])][ \t]*;?[ \t]*$)"
)

#: A keyword score; anything at or above this is trusted vocabulary, not a token
#: that merely happens to appear in the snippet.
TRUSTED = 1000


def _vocabulary(masked, lang):
    """Language keywords (trusted) plus identifiers seen in this snippet."""
    counts = Counter(_IDENT_RE.findall(masked))
    vocab = Counter()
    for word, n in counts.items():
        vocab[word.lower()] += n
    for word in lang.vocabulary:
        vocab[word] += TRUSTED
    return vocab, counts


def _strip_edge_junk(masked, vocab):
    """Drop the stray glyph a clipped screenshot glues onto the line's first token."""
    out = []
    for line in masked.split("\n"):
        line = _EDGE_LINE_RE.sub("", line, count=1)
        match = re.match(r"^([ \t]*)([A-Za-z_][A-Za-z_0-9]*)", line)
        if match:
            indent, token = match.groups()
            # the mangled token is itself in `vocab` (it was read from this
            # snippet), so trust is what distinguishes it from the real word
            if (len(token) > 2 and token[0] in _EDGE_JUNK
                    and vocab.get(token.lower(), 0) < TRUSTED
                    and vocab.get(token[1:].lower(), 0) >= TRUSTED):
                line = indent + token[1:] + line[match.end():]
        out.append(line)
    return "\n".join(out)


# ident, separator, then a lookahead at the next token. The right-hand token is
# deliberately *not* consumed, so it can still act as the left-hand side of the
# next join -- otherwise `std logic vector` would only ever get one underscore.
_SPLIT_RE = re.compile(
    r"([A-Za-z_][A-Za-z_0-9]*)([ \t]*_[ \t]*|[ \t]+)(?=([A-Za-z_0-9]+))")


def _rejoin_underscores(masked, vocab, lang):
    """``std logic vector`` / ``rising _edge`` -> ``std_logic_vector`` / ``rising_edge``.

    Only fires when the joined name is a language keyword or already appears in
    the snippet, so ordinary ``end process`` style pairs are left alone.
    """
    keywords = lang.vocabulary

    for _ in range(6):  # one pass per underscore in the name
        out, pos, changed = [], 0, False
        for match in _SPLIT_RE.finditer(masked):
            if match.start() < pos:
                continue
            left, sep, right = match.group(1), match.group(2), match.group(3)
            # two bare keywords side by side is normal syntax, not a lost underscore
            if ("_" not in sep
                    and left.lower() in keywords and right.lower() in keywords):
                continue
            joined = left.rstrip("_") + "_" + right.lstrip("_")
            if joined.lower() not in vocab:
                continue
            out.append(masked[pos:match.start()])
            out.append(left.rstrip("_") + "_")
            # drop the separator, plus any underscores already on the right token
            pos = match.end() + len(right) - len(right.lstrip("_"))
            changed = True
        if not changed:
            break
        out.append(masked[pos:])
        masked = "".join(out)
    return masked


def _repair_confusables(masked, vocab):
    """``arrayl`` -> ``array1`` when the snippet itself shows the right spelling."""
    cache = {}

    def best(token):
        if token in cache:
            return cache[token]
        winner, score = token, vocab.get(token.lower(), 0)
        last = len(token) - 1
        for i, char in enumerate(token):
            for alternative in CONFUSABLE.get(char, ""):
                # Never turn a trailing digit into a letter. Tesseract misreads
                # `1` as `l`/`i` far more often than the reverse, so the wrong
                # spelling can out-number the right one -- and then a plain
                # frequency vote would corrupt the occurrences it read correctly.
                if i == last and char.isdigit() and not alternative.isdigit():
                    continue
                candidate = token[:i] + alternative + token[i + 1:]
                count = vocab.get(candidate.lower(), 0)
                if count > score:
                    winner, score = candidate, count
        cache[token] = winner
        return winner

    return _IDENT_RE.sub(lambda m: best(m.group()), masked)


#: Letters Tesseract substitutes for a digit at the end of an identifier.
#: `s`/`B`/`Z` are deliberately absent: they are plausible word endings.
DIGIT_LOOKALIKE = {"l": "1", "I": "1", "|": "1", "i": "1",
                   "O": "0", "o": "0", "Q": "0", "D": "0"}


def _repair_digit_siblings(masked, vocab):
    """Resolve a trailing digit that came back as a look-alike letter.

    Two independent kinds of evidence, both drawn from the snippet itself:

    * a **numbered sibling** -- ``cnt2`` exists, so ``cntl``/``cnti`` are ``cnt1``;
    * an **unstable last glyph** -- the same stem came back as both ``vall`` and
      ``vali``, so that position is a digit the OCR could not pin down.

    Both require same-stem evidence, which is what keeps ordinary names ending in
    `l` or `i` (``sel``, ``rtl``, ``total``) untouched: nothing in the snippet
    ever spells them with a digit.
    """
    counts = Counter(_IDENT_RE.findall(masked))

    digit_forms, letter_forms = {}, {}
    for word in counts:
        if len(word) < 2 or vocab.get(word.lower(), 0) >= TRUSTED:
            continue
        stem, last = word[:-1], word[-1]
        if last.isdigit():
            digit_forms.setdefault(stem, set()).add(last)
        elif last in DIGIT_LOOKALIKE:
            letter_forms.setdefault(stem, set()).add(last)

    def fix(match):
        token = match.group()
        if len(token) < 2 or vocab.get(token.lower(), 0) >= TRUSTED:
            return token
        stem, last = token[:-1], token[-1]
        if last not in DIGIT_LOOKALIKE:
            return token
        if digit_forms.get(stem) or len(letter_forms.get(stem, ())) >= 2:
            return stem + DIGIT_LOOKALIKE[last]
        return token

    return _IDENT_RE.sub(fix, masked)


def _differ_by_one(a, b):
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def _repair_rare_tokens(masked, vocab, min_support=3, min_length=5):
    """Fold a one-off misreading into the spelling the snippet uses repeatedly.

    ``ZdigerTail`` appears once, ``ZeigerTail`` four times and they differ by a
    single glyph -- almost certainly the same identifier. Requiring a *unique*
    frequent neighbour keeps this from merging genuinely different names.
    """
    counts = Counter(_IDENT_RE.findall(masked))
    frequent = [w for w, n in counts.items() if n >= min_support and len(w) >= min_length]
    if not frequent:
        return masked

    def fix(match):
        token = match.group()
        if (len(token) < min_length or counts.get(token, 0) != 1
                or vocab.get(token.lower(), 0) >= TRUSTED):
            return token
        candidates = [w for w in frequent if w != token and _differ_by_one(token, w)]
        return candidates[0] if len(candidates) == 1 else token

    return _IDENT_RE.sub(fix, masked)


# --------------------------------------------------------------------------- #
#  4. Punctuation spacing
# --------------------------------------------------------------------------- #

#: Words that keep the space before an opening parenthesis, because there it is
#: syntax rather than a call. Every VHDL reserved word qualifies (`is (`, `not (`,
#: `port (`); in C it is just the control keywords.
SPACED_CALL = {
    "c": {"if", "for", "while", "switch", "return", "sizeof", "do", "else"},
    "vhdl": languages.VHDL_RESERVED,
}


#: A statement-ending `;` misread as the digit that looks like it.
_TRAILING_SEMICOLON_RE = re.compile(r"([)\]}])[5Ss][ \t]*$", re.M)

#: A capital ``O`` sitting where only a number can go, e.g. ``for(i=O;``.
#: Just ``O``: `l`/`o` are plausible variable names, and `Q`/`D` are the standard
#: names for flip-flop ports in VHDL, so neither may be rewritten. The trailing
#: ``=(?!>)`` keeps ``port map (Q => sig)`` out of reach.
_LETTER_AS_ZERO_RE = re.compile(
    r"(?<=[=(,\[<>+\-*/])([ \t]*)O(?=[ \t]*(?:[;,)\]]|[<>+\-*/]|=(?!>)))")

#: A stray tick or dot the OCR hangs off the end of a keyword: ``in' std_logic``.
_KEYWORD_TAIL_RE = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]*)['.](?=[ \t]+[A-Za-z_])")

#: ``(others = '0')`` is never valid; the association arrow lost its head.
_VHDL_OTHERS_ARROW_RE = re.compile(r"\bothers\b([ \t]*)=(?![>=])")

#: Ring-shaped symbols Tesseract returns for a `0` -- `©` is the usual one in a
#: code font, where the zero often carries a slash or dot through it.
_ZERO_LOOKALIKE_RE = re.compile(r"[@©®Ⓞ⊙◎◯○●〇¤]")


def _fix_punctuation(masked, lang):
    """Repairs for punctuation the vocabulary passes can't reach.

    None of the zero look-alikes is legal in C or VHDL outside a string or a
    comment, and both are masked out by this point, so any that remain are
    misread digits.
    """
    masked = _ZERO_LOOKALIKE_RE.sub("0", masked)
    masked = _TRAILING_SEMICOLON_RE.sub(r"\1;", masked)
    masked = _LETTER_AS_ZERO_RE.sub(r"\g<1>0", masked)

    keywords = lang.vocabulary
    masked = _KEYWORD_TAIL_RE.sub(
        lambda m: m.group(1) if m.group(1).lower() in keywords else m.group(), masked)

    if lang.key == "vhdl":
        masked = _VHDL_OTHERS_ARROW_RE.sub(r"others\g<1>=>", masked)
    return masked


def _fix_spacing(masked, lang):
    masked = re.sub(r"[ \t]+([;,)\]])", r"\1", masked)
    masked = re.sub(r"([(\[])[ \t]+", r"\1", masked)

    spaced = SPACED_CALL.get(lang.key, set())

    def tighten(match):
        name = match.group(1)
        return match.group() if name.lower() in spaced else name + "("

    masked = re.sub(r"([A-Za-z_][A-Za-z_0-9]*)[ \t]+\(", tighten, masked)
    masked = re.sub(r"[ \t]+$", "", masked, flags=re.M)
    return masked


# --------------------------------------------------------------------------- #
#  5. Language-specific segment repair
# --------------------------------------------------------------------------- #

_VHDL_CHAR_RE = re.compile(r"^'(.)'$")


def _fix_segments(segments, lang):
    """Repair inside literals, where the vocabulary can't help."""
    if lang.key != "vhdl":
        return segments
    fixed = []
    for seg in segments:
        match = _VHDL_CHAR_RE.match(seg)
        if match:
            ch = match.group(1)
            if ch not in languages.VHDL_LOGIC_VALUES:
                ch = languages.VHDL_LOGIC_CONFUSIONS.get(ch, ch)
            seg = f"'{ch}'"
        fixed.append(seg)
    return fixed


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #

def fix_code(text, lang="auto", reindent=True):
    """Clean up OCR'd source code.

    `lang` is a key from :mod:`src.languages` (``"c"``, ``"vhdl"``) or ``"auto"``
    to detect it from the text. Returns the repaired source.
    """
    if not text:
        return ""

    text = normalize_unicode(text).replace("\r\n", "\n").replace("\r", "\n")

    language = languages.detect(text) if lang in (None, "", "auto") else languages.get(lang)

    masked, segments = _mask(text, language)
    vocab, _counts = _vocabulary(masked, language)

    masked = _fix_punctuation(masked, language)
    masked = _strip_edge_junk(masked, vocab)
    masked = _rejoin_underscores(masked, vocab, language)

    # rejoining changed which identifiers exist, so re-count before voting on them
    vocab, _counts = _vocabulary(masked, language)
    # Digit repair runs first: it reads the *spread* of misspellings as evidence,
    # and the frequency vote below would collapse that spread into one spelling.
    masked = _repair_digit_siblings(masked, vocab)
    masked = _repair_confusables(masked, vocab)
    masked = _repair_rare_tokens(masked, vocab)
    masked = _fix_spacing(masked, language)

    text = _unmask(masked, _fix_segments(segments, language))

    lines = text.split("\n")
    if reindent:
        # Only the *leading* whitespace is rebuilt; runs of spaces inside a line
        # are column alignment the author put there on purpose.
        lines = language.indenter([line.strip() for line in lines])
    return "\n".join(lines).strip("\n") + "\n"


def detect_language(text):
    """Return the language key (``"c"`` / ``"vhdl"``) that best fits `text`."""
    return languages.detect(text).key


def fix_c_ocr(text):
    """Backwards-compatible entry point: repair a snippet as C."""
    return fix_code(text, lang="c")
