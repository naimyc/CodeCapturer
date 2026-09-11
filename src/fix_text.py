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


#: A line that begins with nothing but an integer -- a candidate gutter entry.
_GUTTER_RE = re.compile(r"^[ \t]*(\d{1,5})(?=[ \t]|$)")

#: Once a gutter is confirmed, tolerate one stray glyph stuck to the number.
_GUTTER_LOOSE_RE = re.compile(r"^([ \t]*[^\s\d]?\d{1,5})(?=[ \t]|$)")


def strip_line_numbers(text):
    """Blank out an editor's line-number gutter, if the snippet clearly has one.

    Screenshots are usually taken with line numbers showing, and OCR reads that
    column as if it were code: the numbers land in the vocabulary, wreck the
    indentation and split statements. Detection leans on the fact that a gutter
    numbers *every* line and counts up one at a time, which ordinary source
    never does -- a `0 => "00"` lookup table has no number on its blank lines
    and does not span the whole snippet.

    The digits are replaced by spaces rather than removed, so every column to
    the right of the gutter stays where it was.
    """
    lines = text.split("\n")
    found = []
    for index, line in enumerate(lines):
        match = _GUTTER_RE.match(line)
        if match:
            found.append((index, int(match.group(1)), match.end(1)))

    populated = sum(1 for line in lines if line.strip())
    if len(found) < 5 or not populated or len(found) < populated * 0.6:
        return text

    numbers = [n for _, n, _ in found]
    rising = sum(1 for a, b in zip(numbers, numbers[1:]) if b > a)
    if rising < (len(numbers) - 1) * 0.8:
        return text
    steps = sorted(b - a for a, b in zip(numbers, numbers[1:]))
    if not steps or steps[len(steps) // 2] != 1:
        return text
    # a gutter counts the lines it sits next to; a data column would not
    if not len(found) <= numbers[-1] - numbers[0] + 1 <= len(lines) * 1.5:
        return text

    # The gutter is confirmed, so now sweep it off *every* line -- including the
    # ones where OCR glued a stray glyph onto the number and the strict pattern
    # above did not match them.
    out = [_GUTTER_LOOSE_RE.sub(lambda m: " " * len(m.group(1)), line, count=1)
           for line in lines]
    return _dedent(out)


def _dedent(lines):
    """Drop the indentation every line shares, left behind by the gutter."""
    common = min((len(line) - len(line.lstrip(" "))
                  for line in lines if line.strip()), default=0)
    if not common:
        return "\n".join(lines)
    return "\n".join(line[common:] if line.strip() else "" for line in lines)


# --------------------------------------------------------------------------- #
#  2. Literal / comment masking
# --------------------------------------------------------------------------- #

_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile("\x00(\\d+)\x00")


def _segment_re(lang):
    parts = list(lang.literals)          # e.g. Python docstrings, matched first
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


#: Junk that can precede a keyword at the start of a line. Deliberately narrow:
#: `(`, `*`, `&`, `-` and `#` all begin legitimate lines of C.
_LEADING_JUNK_RUN = re.compile(r"^([ \t]*)([<>|¦!~]{1,2})([A-Za-z_][A-Za-z_0-9]*)")


def _split_glued_keyword(masked, vocab, lang):
    """``inti`` -> ``int i``: a keyword that lost the space after it.

    Needs the leading keyword *and* a tail the snippet already uses, so
    ``intern`` and ``integer`` are safe -- neither `ern` nor `eger` is a name
    here -- and only fires on a spelling seen once, so a real `chars` survives.
    """
    keywords = sorted((w for w in lang.vocabulary if len(w) >= 2),
                      key=len, reverse=True)
    counts = Counter(_IDENT_RE.findall(masked))

    def fix(match):
        token = match.group()
        if counts.get(token, 0) != 1 or vocab.get(token.lower(), 0) >= TRUSTED:
            return token
        lowered = token.lower()
        for word in keywords:
            if not lowered.startswith(word) or len(token) == len(word):
                continue
            tail = token[len(word):]
            if not tail[:1].isalpha() and tail[:1] != "_":
                continue
            if vocab.get(tail.lower(), 0) >= TRUSTED or counts.get(tail, 0) >= 2:
                return token[:len(word)] + " " + tail
        return token

    return _IDENT_RE.sub(fix, masked)


def _strip_edge_junk(masked, vocab):
    """Drop the stray glyph a clipped screenshot glues onto the line's first token."""
    out = []
    for line in masked.split("\n"):
        line = _EDGE_LINE_RE.sub("", line, count=1)
        # a run of stray glyphs jammed against a keyword, e.g. `<<int i;`
        run = _LEADING_JUNK_RUN.match(line)
        if run and vocab.get(run.group(3).lower(), 0) >= TRUSTED:
            line = run.group(1) + line[run.end(2):]
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
    r"([A-Za-z_][A-Za-z_0-9]*)(?:[ \t]+_[ \t]+|[ \t]+)(?=([A-Za-z_0-9]+))")


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
            left, right = match.group(1), match.group(2)
            # two bare keywords side by side is normal syntax, not a lost underscore
            if left.lower() in keywords and right.lower() in keywords:
                continue
            # strip at most one underscore per side: the separator supplies
            # one, but `__init__` needs the rest of its own kept
            stem = left[:-1] if left.endswith("_") else left
            tail = right[1:] if right.startswith("_") else right
            joined = stem + "_" + tail
            if joined.lower() not in vocab:
                continue
            out.append(masked[pos:match.start()])
            out.append(stem + "_")
            pos = match.end() + (len(right) - len(tail))
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


def _trailing_skeleton(word):
    """Normalise a trailing digit look-alike, so `arrayl` and `array1` agree."""
    if len(word) > 1 and word[-1] in DIGIT_LOOKALIKE:
        return word[:-1] + DIGIT_LOOKALIKE[word[-1]]
    return word


#: Glyphs Tesseract returns for `&`. `S` and `G` are identifier characters, so
#: the misread operator fuses onto the name behind it and the whole thing comes
#: back looking like one word: `&array1` -> `Sarray1`.
_GLUED_AMPERSAND_RE = re.compile(
    r"(?<![A-Za-z_0-9])([SG$8]&?|&[SG$8])([A-Za-z_][A-Za-z_0-9]*)")

#: Characters a unary `&` may directly follow.
_OPERAND_START = set("(,=[{<>+-*/%|^!~?:;&")


def _repair_glued_ampersand(masked, vocab, lang):
    """``mul(Sarray1[0])`` -> ``mul(&array1[0])``.

    Address-of is written tight against its operand, so a misread `&` does not
    leave a separate token to repair -- it has to be split back off. Three things
    have to hold before that happens: the tail must be a name the snippet already
    uses, the fused form must be rarer than that name, and the whole thing must
    sit where a unary operator is actually legal. Together those stop a variable
    that genuinely starts with `S` from being rewritten.
    """
    keywords = lang.vocabulary
    # Compare on skeletons, not exact spelling: the tail may never have been
    # read correctly anywhere, yet still show up as `arrayl` next to `array1`.
    shapes = Counter(_trailing_skeleton(word.lower())
                     for word in _IDENT_RE.findall(masked))

    def fix(match):
        prefix, name = match.group(1), match.group(2)
        known = shapes.get(_trailing_skeleton(name.lower()), 0)
        if known <= 0:
            return match.group()
        # `Sdata` read as a name in its own right -- if that spelling is more
        # common than `data`, believe it rather than "correcting" it
        if shapes.get(_trailing_skeleton(match.group().lower()), 0) > known:
            return match.group()

        before = masked[:match.start()].rstrip(" \t")
        if before and not before.endswith("\n"):
            if before[-1] not in _OPERAND_START:
                # `return &x;` / `sizeof &x` are operand positions too
                word = re.search(r"[A-Za-z_][A-Za-z_0-9]*$", before)
                if not (word and word.group().lower() in keywords):
                    return match.group()
        return "&" + name

    return _GLUED_AMPERSAND_RE.sub(fix, masked)


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


def _repair_doubled_glyph(masked, vocab):
    """``arrayl1`` -> ``array1``: one ambiguous glyph reported twice.

    Where a shape could be read either as a letter or as a digit, Tesseract
    sometimes emits both, leaving `l1` where the source had a single `1`. The
    give-away is that dropping the letter yields a name the snippet already has.
    """
    counts = Counter(_IDENT_RE.findall(masked))

    def fix(match):
        token = match.group()
        if counts.get(token, 0) != 1 or vocab.get(token.lower(), 0) >= TRUSTED:
            return token
        for i in range(len(token) - 1):
            digit = DIGIT_LOOKALIKE.get(token[i])
            if digit and token[i + 1] == digit:
                candidate = token[:i] + token[i + 1:]
                if vocab.get(candidate.lower(), 0) > 0:
                    return candidate
        return token

    return _IDENT_RE.sub(fix, masked)


def _repair_letter_case(masked):
    """``Z1`` -> ``z1`` when the snippet consistently spells it the other way.

    Case is the whole difference here, which is a far narrower claim than a
    general edit-distance match, so it is safe on short names where the
    frequency repairs below refuse to act.
    """
    counts = Counter(_IDENT_RE.findall(masked))
    by_fold = {}
    for word, seen in counts.items():
        by_fold.setdefault(word.lower(), []).append((seen, word))

    def fix(match):
        token = match.group()
        if counts.get(token, 0) != 1:
            return token
        established = [w for seen, w in by_fold.get(token.lower(), ())
                       if w != token and seen >= 2]
        return established[0] if len(established) == 1 else token

    return _IDENT_RE.sub(fix, masked)


def _differ_by_one(a, b):
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def _within_one_edit(a, b):
    """True when one insert, delete or substitution turns `a` into `b`."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return _differ_by_one(a, b)
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _repair_against_keywords(masked, vocab, lang, min_length=5):
    """``_name__`` -> ``__name__``: snap a near-miss onto a known keyword.

    The candidate set is the fixed language vocabulary rather than the snippet,
    so a *unique* match one edit away is strong evidence. Restricted to
    lower-case spellings so the keyword's own casing can be adopted safely, and
    to names seen once, so a real identifier is never absorbed.
    """
    counts = Counter(_IDENT_RE.findall(masked))
    keywords = [w for w in lang.vocabulary if len(w) >= min_length]

    def fix(match):
        token = match.group()
        if (len(token) < min_length or token != token.lower()
                or counts.get(token, 0) != 1
                or vocab.get(token, 0) >= TRUSTED):
            return token
        hits = [w for w in keywords if _within_one_edit(token, w)]
        return hits[0] if len(hits) == 1 else token

    return _IDENT_RE.sub(fix, masked)


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
ZERO_LOOKALIKES = "@©®Ⓞ⊙◎◯○●〇¤"

_ZERO_LOOKALIKE_RE = re.compile("[" + ZERO_LOOKALIKES + "]")
#: Python spells decorators `@property`, so there `@` is syntax, not a misread.
#: `@property` is a decorator, but a bare `@` is still a misread zero.
_ZERO_LOOKALIKE_DECORATOR_RE = re.compile(
    "[" + ZERO_LOOKALIKES.replace("@", "") + "]" + r"|@(?![A-Za-z_])")


def _zero_lookalike_re(lang):
    return (_ZERO_LOOKALIKE_DECORATOR_RE if lang.at_sign_is_syntax
            else _ZERO_LOOKALIKE_RE)


def _fix_punctuation(masked, lang):
    """Repairs for punctuation the vocabulary passes can't reach.

    None of the zero look-alikes is legal in C or VHDL outside a string or a
    comment, and both are masked out by this point, so any that remain are
    misread digits.
    """
    masked = _zero_lookalike_re(lang).sub("0", masked)
    if lang.uses_semicolons:
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

    spaced = lang.spaced_before_paren

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
    text = strip_line_numbers(text)

    language = languages.detect(text) if lang in (None, "", "auto") else languages.get(lang)

    masked, segments = _mask(text, language)
    vocab, _counts = _vocabulary(masked, language)

    masked = _fix_punctuation(masked, language)
    # split before stripping: `<<inti;` only reveals its keyword once it is
    # spelled `<<int i;`
    masked = _split_glued_keyword(masked, vocab, language)
    masked = _strip_edge_junk(masked, vocab)
    masked = _rejoin_underscores(masked, vocab, language)

    # rejoining changed which identifiers exist, so re-count before voting on them
    vocab, _counts = _vocabulary(masked, language)
    if language.key == "c":
        # only C has a unary `&`; in VHDL it is binary concatenation, and
        # Python has no address-of at all
        masked = _repair_glued_ampersand(masked, vocab, language)
        # the split revealed a name that was not in the vocabulary before
        vocab, _counts = _vocabulary(masked, language)
    # Digit repair runs first: it reads the *spread* of misspellings as evidence,
    # and the frequency vote below would collapse that spread into one spelling.
    masked = _repair_digit_siblings(masked, vocab)
    masked = _repair_doubled_glyph(masked, vocab)
    masked = _repair_letter_case(masked)
    masked = _repair_confusables(masked, vocab)
    masked = _repair_rare_tokens(masked, vocab)
    masked = _repair_against_keywords(masked, vocab, language)
    masked = _fix_spacing(masked, language)

    text = _unmask(masked, _fix_segments(segments, language))

    lines = text.split("\n")
    if reindent:
        if language.rebuilds_indent:
            # Only the *leading* whitespace is rebuilt; runs of spaces inside a
            # line are column alignment the author put there on purpose.
            lines = language.indenter([line.strip() for line in lines])
        else:
            # Python: the indenter may tidy the widths but never invent them.
            lines = language.indenter(lines)
    return "\n".join(lines).strip("\n") + "\n"


def detect_language(text):
    """Return the language key (``"c"``/``"vhdl"``/``"python"``) fitting `text`."""
    return languages.detect(text).key


def fix_c_ocr(text):
    """Backwards-compatible entry point: repair a snippet as C."""
    return fix_code(text, lang="c")
