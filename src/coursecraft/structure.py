"""
Structural parsing shared by reflow.py and lint.py.

This module answers questions about a .qmd file's *structure* --
where fences are, whether a line is real document structure or just
decoration inside a theorem/example div, whether a line is a valid
ordered-list marker -- without making any formatting decisions itself.
"""

import re

CODE_FENCE_RE = re.compile(r'^\s*```')
MATH_FENCE_RE = re.compile(r'^\s*\$\$\s*$')
DIV_FENCE_RE = re.compile(r'^(\s*)(:{3,})(.*)$')
THEMATIC_BREAK_RE = re.compile(r'^\s*([-*_])(?:\s*\1){2,}\s*$')
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)$')
LABEL_RE = re.compile(r'\{#([\w-]+)[^}]*\}')
ATTR_BLOCK_RE = re.compile(r'\{([^}]*)\}\s*$')


class FenceTracker:
    """Tracks code-fence, display-math-fence, and div-fence depth line by
    line. Two distinct notions of 'top level' are exposed:
      - at_structural_top_level(): used when deciding whether a '#'/'##'
        line is real document structure (must be outside code, math, AND
        any div -- a heading inside a .theorem div is a decorative title,
        not a section).
      - in_protected_block(): used when deciding whether prose text may be
        reflowed. Code and display-math blocks are hard-protected. So is
        any .lproof div, in full, regardless of what its individual lines
        look like -- lproof's own parser reads its content as raw text
        (each line indented >=4 spaces, carrying its own line number), so
        reflow must never rejoin, rewrap, or trim anything inside one.
        Protection is inherited by anything nested inside an .lproof div.
    """

    def __init__(self):
        self.in_code = False
        self.in_math = False
        self.div_depth = 0
        self.lproof_stack = []  # one bool per open div: is it (or its parent) lproof?

    def at_structural_top_level(self):
        return (not self.in_code) and (not self.in_math) and self.div_depth == 0

    def in_protected_block(self):
        if self.in_code or self.in_math:
            return True
        return bool(self.lproof_stack) and self.lproof_stack[-1]

    def consume(self, line):
        """Update state for this line, return True if this line itself
        is a fence delimiter (code, math, or div) rather than content."""
        if CODE_FENCE_RE.match(line):
            self.in_code = not self.in_code
            return True
        if self.in_code:
            return False
        if MATH_FENCE_RE.match(line):
            self.in_math = not self.in_math
            return True
        if self.in_math:
            return False
        m = DIV_FENCE_RE.match(line)
        if m:
            rest = m.group(3).strip()
            if rest:  # opening fence, e.g. ':::{.content-hidden ...}'
                self.div_depth += 1
                is_lproof = bool(re.search(r'\.lproof\b', rest))
                inherited = bool(self.lproof_stack) and self.lproof_stack[-1]
                self.lproof_stack.append(is_lproof or inherited)
            else:     # bare ':::' -- closes the innermost open div
                if self.div_depth > 0:
                    self.div_depth -= 1
                if self.lproof_stack:
                    self.lproof_stack.pop()
            return True
        return False


def slugify(text: str) -> str:
    """Turn heading text into a url/label-safe slug: strip inline math,
    footnote markers, existing {#...} attrs, and LaTeX macros first."""
    text = re.sub(r'\$[^$]*\$', '', text)
    text = LABEL_RE.sub('', text)
    text = re.sub(r'\[\^[^\]]*\]', '', text)
    text = re.sub(r'\\[A-Za-z]+', '', text)
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


# --- ordinary (non-lproof) numbered/lettered/roman-numeral list markers ---

_ROMAN_WHITELIST = {
    'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x',
    'xi', 'xii', 'xiii', 'xiv', 'xv',
}

LIST_ITEM_RE = re.compile(r'^(\s*)(\(?)([a-zA-Z]+|\d+)(\)|[.)])(\.)?(\s+)(.*)$')


def is_ordered_list_marker(letters_or_digits: str) -> bool:
    """A numeric marker (1, 2, 23, ...) is always valid. A letter marker
    is valid only if it's a single letter (a, b, ... -- an ordinary
    lettered list) or a recognized lowercase roman numeral (i, ii, iii,
    iv, ...) -- this avoids matching an ordinary word that happens to
    start a line and be followed by a period, e.g. 'The. next sentence'."""
    if letters_or_digits.isdigit():
        return True
    lowered = letters_or_digits.lower()
    if len(letters_or_digits) == 1 and letters_or_digits.isalpha():
        return True
    return lowered in _ROMAN_WHITELIST


def line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(' '))


def is_fence_line(line: str) -> bool:
    """True for a code fence, display-math fence, div fence delimiter,
    or a Markdown thematic break (a bare '---', '***', '___', etc.).
    These always end a list region immediately, regardless of
    indentation -- and, in the reflow loop, must never be merged into
    surrounding prose. A thematic break merged into a paragraph gets
    converted by Pandoc's smart-typography into a literal em-dash
    instead of staying a horizontal rule -- confirmed by direct
    reproduction, not a hypothetical."""
    return bool(CODE_FENCE_RE.match(line) or MATH_FENCE_RE.match(line)
                or DIV_FENCE_RE.match(line) or THEMATIC_BREAK_RE.match(line))


def blank_gap_continues_list(lines, j, base_indent):
    """After a run of blank lines ending just before index j, decide
    whether the list region continues: yes if the next content line is
    indented strictly more than base_indent (a continuation paragraph),
    or is itself a valid sibling item at exactly base_indent. A line at
    base_indent that is NOT a list item means ordinary prose has resumed
    at the margin, so the list has ended. A fence line always ends it."""
    if j >= len(lines):
        return False
    line = lines[j]
    if is_fence_line(line):
        return False
    indent = line_indent(line)
    if indent > base_indent:
        return True
    if indent == base_indent:
        m = LIST_ITEM_RE.match(line)
        return bool(m and is_ordered_list_marker(m.group(3)))
    return False
