"""
Reflow .qmd files: semantic-linebreak mode (one sentence per line, the
default) or column-wrap mode. Fence-aware and .lproof-safe throughout --
see structure.py for the shared parsing this builds on.
"""

import re
from typing import Optional

from .structure import (
    FenceTracker,
    THEMATIC_BREAK_RE,
    LIST_ITEM_RE,
    is_ordered_list_marker,
    line_indent,
    is_fence_line,
    blank_gap_continues_list,
    _ROMAN_WHITELIST,
)

MATH_OR_ATOMIC_RE = re.compile(
    r'(\$\$[^$]*\$\$|\$[^$]*\$|\[\^[^\]]+\]|\[@[^\]]+\]|\{\{<[^>]*>\}\})'
)

NON_PARAGRAPH_START_RE = re.compile(
    r'^\s*(#|:::|-{1}\s|\*\s|\+\s|>|\||`|\{\{<)'
)

INDENTED_CONTINUATION_RE = re.compile(r'^(    |\t)')


# ---------------------------------------------------------------------------
# Ordered-list reflow (hanging indent, recursive nested-list handling)
# ---------------------------------------------------------------------------

def reflow_list_region(lines, width):
    """Reflow one contiguous (possibly multi-paragraph, possibly nested)
    ordered-list region starting at lines[0] (which must be a valid list
    item). Consumes as many lines as belong to this list -- stopping at
    a dedent below the first item's indentation -- and returns
    (rendered_lines, number_of_input_lines_consumed); trailing lines are
    left for the caller."""
    out = []
    i = 0
    n = len(lines)
    m0 = LIST_ITEM_RE.match(lines[0])
    base_indent = len(m0.group(1))

    while i < n:
        line = lines[i]
        if is_fence_line(line):
            break  # structural fence (e.g. a div closing) -- never list content
        if line.strip() == '':
            j = i
            while j < n and lines[j].strip() == '':
                j += 1
            if not blank_gap_continues_list(lines, j, base_indent):
                break
            out.append('')
            i += 1
            continue
        indent = line_indent(line)
        if indent < base_indent:
            break
        m = LIST_ITEM_RE.match(line)
        if m and indent == base_indent and is_ordered_list_marker(m.group(3)):
            item_indent, open_paren, core, closer, extra_dot, spacer, first_text = m.groups()
            full_marker = open_paren + core + closer + (extra_dot or '')
            hang_col = len(item_indent) + len(full_marker) + 1
            marker_prefix = item_indent + full_marker + ' '

            body = []
            i += 1
            while i < n:
                nxt = lines[i]
                if is_fence_line(nxt):
                    break
                if nxt.strip() == '':
                    j = i
                    while j < n and lines[j].strip() == '':
                        j += 1
                    if not blank_gap_continues_list(lines, j, base_indent):
                        break
                    body.append(nxt)
                    i += 1
                    continue
                nxt_indent = line_indent(nxt)
                if nxt_indent < base_indent:
                    break
                nxt_m = LIST_ITEM_RE.match(nxt)
                if (nxt_indent == base_indent and nxt_m
                        and is_ordered_list_marker(nxt_m.group(3))):
                    break  # sibling item at the same level
                body.append(nxt)
                i += 1

            rendered = _render_item_body(first_text, body, hang_col, width)
            hang_prefix = ' ' * hang_col
            if rendered:
                first_out = rendered[0]
                rest = first_out[hang_col:] if first_out.startswith(hang_prefix) else first_out.lstrip()
                out.append(marker_prefix + rest)
                out.extend(rendered[1:])
            else:
                out.append(marker_prefix.rstrip())
            continue
        else:
            break
    return out, i


def _render_item_body(first_text, body_lines, hang_col: int, width):
    """Render one list item's own text plus its continuation lines.
    Splits on blank lines into paragraphs; a paragraph that starts with a
    deeper-indented list marker is instead treated as a nested sub-list
    and reflowed recursively via reflow_list_region."""
    hang_prefix = ' ' * hang_col
    out_lines = []
    blocks = []  # list of ('prose', [lines]) | ('blank',) | ('nested', [lines])
    cur_prose = [first_text] if first_text.strip() else []
    cur_nested = None

    def flush_prose():
        nonlocal cur_prose
        if cur_prose:
            blocks.append(('prose', cur_prose))
            cur_prose = []

    def flush_nested():
        nonlocal cur_nested
        if cur_nested:
            blocks.append(('nested', cur_nested))
            cur_nested = None

    for line in body_lines:
        if line.strip() == '':
            flush_prose()
            flush_nested()
            blocks.append(('blank',))
            continue
        indent = line_indent(line)
        m = LIST_ITEM_RE.match(line)
        is_nested_start = indent > 0 and m and is_ordered_list_marker(m.group(3))
        if is_nested_start:
            flush_prose()
            if cur_nested is None:
                cur_nested = [line]
            else:
                cur_nested.append(line)
        elif cur_nested is not None:
            cur_nested.append(line)
        else:
            cur_prose.append(line)
    flush_prose()
    flush_nested()

    for block in blocks:
        if block[0] == 'blank':
            out_lines.append('')
        elif block[0] == 'prose':
            text = ' '.join(l.strip() for l in block[1] if l.strip() != '')
            wrapped = _wrap_paragraph(text, width if width is None else max(width - hang_col, 20))
            for wl in wrapped.split('\n'):
                out_lines.append(hang_prefix + wl)
        elif block[0] == 'nested':
            rendered_nested, consumed = reflow_list_region(block[1], width)
            out_lines.extend(rendered_nested)
            leftover = block[1][consumed:]
            if leftover:
                text = ' '.join(l.strip() for l in leftover if l.strip() != '')
                if text:
                    wrapped = _wrap_paragraph(text, width if width is None else max(width - hang_col, 20))
                    for wl in wrapped.split('\n'):
                        out_lines.append(hang_prefix + wl)
    return out_lines


# ---------------------------------------------------------------------------
# Tokenization, wrapping, and the two paragraph-wrap strategies
# ---------------------------------------------------------------------------

def _tokenize_preserving_adjacency(text: str):
    """Scan left to right. Protected spans (math/footnotes/citations/
    shortcodes) are single tokens with their REAL text and length. Any
    token directly adjacent to the previous one (no whitespace between
    them in the source -- e.g. 'valuation?[^note]' or '[^note]:') is
    merged onto it rather than getting a space inserted. This matters:
    a space wrongly inserted before a footnote definition's ':' stops
    Pandoc from recognizing it as a footnote at all."""
    spans = {m.start(): m.end() for m in MATH_OR_ATOMIC_RE.finditer(text)}
    n = len(text)
    i = 0
    prev_end = None
    merged = []
    while i < n:
        if i in spans:
            end = spans[i]
            piece = text[i:end]
        elif text[i].isspace():
            i += 1
            prev_end = None
            continue
        else:
            j = i
            while j < n and not text[j].isspace() and j not in spans:
                j += 1
            end = j
            piece = text[i:end]

        if prev_end == i and merged:
            merged[-1] += piece
        else:
            merged.append(piece)
        prev_end = end
        i = end
    return merged


DANGEROUS_LINE_START_RE = re.compile(
    r'^(\d+[.)]|[a-zA-Z][.)]|(?:'
    + '|'.join(sorted(_ROMAN_WHITELIST, key=len, reverse=True))
    + r')[.)]|@[\w-]+\))(\s|$)'
)


def _fix_dangerous_line_starts(lines):
    """A wrapped continuation line that happens to start with something
    matching an ordered-list marker (e.g. a bare year like '1975.', or a
    Pandoc example-list ref like '@fig-x)') gets misparsed by Pandoc as
    starting a brand new list, mid-sentence -- confirmed by direct testing,
    not a hypothetical. If a candidate line would start that way, the
    offending leading token is glued onto the end of the previous line
    instead, even if that pushes it slightly past the target width;
    correctness wins over exact width here."""
    fixed = list(lines)
    i = 1
    while i < len(fixed):
        m = DANGEROUS_LINE_START_RE.match(fixed[i])
        if m and i > 0:
            token = fixed[i][:m.end(1)]
            rest = fixed[i][m.end(1):].lstrip()
            fixed[i - 1] = fixed[i - 1] + ' ' + token
            if rest:
                fixed[i] = rest
            else:
                del fixed[i]
                continue
        i += 1
    return fixed


_ABBREVIATIONS = {
    'e.g', 'i.e', 'cf', 'etc', 'vs', 'mr', 'mrs', 'ms', 'dr', 'prof', 'st',
    'vol', 'no', 'p', 'pp', 'op', 'art', 'ca', 'approx', 'resp', 'viz',
    'al', 'fig', 'eq', 'sec', 'ch', 'trans', 'ed', 'eds', 'rev',
}

SENTENCE_SPLIT_RE = re.compile(r'([.!?])([\'")\]]*)(\s+)')


def _split_sentences(text: str):
    """Split a paragraph into one chunk per sentence, for semantic-
    linebreak mode. Conservative: a candidate split is skipped if it's
    inside a protected span (math/footnote/citation/shortcode), looks
    like a decimal number, follows a recognized abbreviation, or isn't
    followed by something that looks like the start of a new sentence.
    An occasional wrong guess here is only ever cosmetic -- Pandoc
    rejoins soft-wrapped lines into the same paragraph regardless of
    where they break, so the one real risk (a line accidentally
    starting with something that looks like a new list marker) is
    handled separately by _fix_dangerous_line_starts, applied after."""
    protected = [(m.start(), m.end()) for m in MATH_OR_ATOMIC_RE.finditer(text)]

    def in_protected(pos):
        return any(s <= pos < e for s, e in protected)

    chunks = []
    last = 0
    for m in SENTENCE_SPLIT_RE.finditer(text):
        term_pos = m.start(1)
        if in_protected(term_pos):
            continue
        before = text[term_pos - 1] if term_pos > 0 else ''
        after_idx = m.end(2)
        after = text[after_idx] if after_idx < len(text) else ''
        if m.group(1) == '.' and before.isdigit() and after.isdigit():
            continue  # decimal number, e.g. '3.14'
        word_start = term_pos
        while word_start > 0 and (text[word_start - 1].isalnum() or text[word_start - 1] == '.'):
            word_start -= 1
        word = text[word_start:term_pos].lower()
        if word in _ABBREVIATIONS:
            continue
        next_start = m.end()
        nxt = text[next_start] if next_start < len(text) else ''
        if nxt and not (nxt.isupper() or nxt.isdigit() or nxt in '([{$'):
            continue
        split_at = m.end()
        chunk = text[last:split_at].strip()
        if chunk:
            chunks.append(chunk)
        last = split_at
    tail = text[last:].strip()
    if tail:
        chunks.append(tail)
    return chunks


def _wrap_paragraph(text: str, width: Optional[int]) -> str:
    """width=None selects semantic-linebreak mode (one sentence per
    output line); an integer selects column-wrap mode at that width."""
    if width is None:
        lines = _split_sentences(text)
    else:
        tokens = _tokenize_preserving_adjacency(text)
        lines = []
        cur = []
        cur_len = 0
        for tok in tokens:
            add_len = len(tok) + (1 if cur else 0)
            if cur and cur_len + add_len > width:
                lines.append(' '.join(cur))
                cur = [tok]
                cur_len = len(tok)
            else:
                cur.append(tok)
                cur_len += add_len
        if cur:
            lines.append(' '.join(cur))
    lines = _fix_dangerous_line_starts(lines)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def reflow(text: str, width: Optional[int] = None) -> str:
    """Reflow a .qmd file's text. width=None (the default) is semantic-
    linebreak mode; an integer selects column-wrap mode at that width."""
    lines = text.split('\n')

    # Pass through a leading YAML frontmatter block (--- ... ---) verbatim;
    # it's structured metadata, not prose, and must never be reflowed.
    front_matter = []
    if lines and lines[0].strip() == '---':
        front_matter.append(lines[0])
        i = 1
        while i < len(lines):
            front_matter.append(lines[i])
            if lines[i].strip() == '---':
                i += 1
                break
            i += 1
        lines = lines[i:]

    out = []
    tracker = FenceTracker()
    para_buf = []

    def flush_para():
        if para_buf:
            joined = ' '.join(l.strip() for l in para_buf)
            out.append(_wrap_paragraph(joined, width))
            para_buf.clear()

    prev_blank = None  # None = start of file (don't force a leading blank)
    i = 0
    n = len(lines)
    while i < n:
        raw_line = lines[i]
        line = raw_line.rstrip()
        is_fence = tracker.consume(line)

        if is_fence:
            flush_para()
            out.append(raw_line)
            prev_blank = False
            i += 1
            continue

        if THEMATIC_BREAK_RE.match(line):
            # a bare '---'/'***'/'___' horizontal rule -- merging this
            # into a paragraph (as ordinary reflow would) makes Pandoc's
            # smart-typography extension convert it into a literal em-dash
            # instead of keeping it a horizontal rule. Confirmed by direct
            # reproduction, not a hypothetical.
            flush_para()
            out.append(raw_line)
            prev_blank = False
            i += 1
            continue

        if tracker.in_protected_block():
            # inside code, display-math, or an .lproof div: pass through
            # completely untouched, not even trailing-whitespace trimmed --
            # lproof in particular parses its content as raw text (exact
            # indentation and line numbers matter), so nothing here may
            # be rejoined, rewrapped, or trimmed.
            flush_para()
            out.append(raw_line)
            prev_blank = (line.strip() == '')
            i += 1
            continue

        if line.strip() == '':
            flush_para()
            if prev_blank is False or prev_blank is None:
                out.append('')
            prev_blank = True
            i += 1
            continue

        list_m = LIST_ITEM_RE.match(line)
        if list_m and is_ordered_list_marker(list_m.group(3)):
            # ordinary numbered/lettered/roman list item: reflow with a
            # hanging indent (much more readable than a raw, unwrapped
            # source line), recursing into any nested sub-list.
            flush_para()
            rendered, consumed = reflow_list_region(lines[i:], width)
            out.extend(rendered)
            prev_blank = (rendered[-1].strip() == '') if rendered else prev_blank
            i += consumed
            continue

        if NON_PARAGRAPH_START_RE.match(line):
            flush_para()
            out.append(raw_line)
            prev_blank = False
            i += 1
            continue

        if INDENTED_CONTINUATION_RE.match(raw_line):
            # 4-space/tab indented line: a footnote or list-item
            # continuation paragraph. Pandoc requires this exact
            # indentation to keep it attached to its parent block --
            # stripping it (as normal reflow would) silently detaches
            # the paragraph, turning it into ordinary inline text.
            # Left untouched rather than risk corrupting it.
            flush_para()
            out.append(raw_line)
            prev_blank = False
            i += 1
            continue

        # plain paragraph text -- accumulate for reflow
        para_buf.append(line)
        prev_blank = False
        i += 1

    flush_para()

    # collapse any remaining runs of 2+ blank lines to exactly 1
    cleaned = []
    for line in out:
        if line == '' and cleaned and cleaned[-1] == '':
            continue
        cleaned.append(line)
    body = '\n'.join(cleaned).strip() + '\n'

    if front_matter:
        return '\n'.join(front_matter) + '\n\n' + body
    return body
