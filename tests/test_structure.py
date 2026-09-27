from coursecraft.structure import (
    FenceTracker,
    slugify,
    is_ordered_list_marker,
    is_fence_line,
    blank_gap_continues_list,
    LIST_ITEM_RE,
    find_headings,
)


def _run(tracker, lines):
    """Feed every line through the tracker, return the list of
    at_structural_top_level() values, one per line."""
    return [
        (not tracker.consume(line)) and tracker.at_structural_top_level()
        for line in lines
    ]


class TestFenceTracker:
    def test_code_fence_protects_content(self):
        t = FenceTracker()
        lines = ["prose", "```", "# not a heading", "```", "prose again"]
        results = [t.consume(l) or t.in_protected_block() for l in lines]
        # inside the fence (index 2), content must be protected
        assert results[2] is True

    def test_math_fence_protects_content(self):
        t = FenceTracker()
        lines = ["prose", "$$", "x = 1", "$$", "prose again"]
        t.consume(lines[0])
        t.consume(lines[1])
        assert t.in_protected_block()
        t.consume(lines[2])
        assert t.in_protected_block()
        t.consume(lines[3])
        assert not t.in_protected_block()

    def test_div_depth_tracks_nesting(self):
        t = FenceTracker()
        for line in ["::: {.example}", ":::{.exercise}", ":::", ":::"]:
            t.consume(line)
        assert t.div_depth == 0

    def test_heading_inside_div_not_structural_top_level(self):
        t = FenceTracker()
        t.consume("::: {.theorem}")
        assert not t.at_structural_top_level()
        t.consume("## Decorative Title")
        assert not t.at_structural_top_level()
        t.consume(":::")
        assert t.at_structural_top_level()

    def test_lproof_protection_inherited_by_nested_div(self):
        """Protection must extend into anything nested inside an .lproof
        div, not just its immediate lines."""
        t = FenceTracker()
        t.consume(":::{.lproof}")
        assert t.in_protected_block()
        t.consume("    1. some raw proof line")
        assert t.in_protected_block()
        t.consume(":::")
        assert not t.in_protected_block()

    def test_non_lproof_div_content_not_protected(self):
        t = FenceTracker()
        t.consume(":::{.example}")
        assert not t.in_protected_block()
        t.consume(":::")


class TestSlugify:
    def test_basic_text(self):
        assert slugify("Why Study Logic?") == "why-study-logic"

    def test_strips_inline_math(self):
        assert slugify("Soundness of $\\mathbf{S}$") == "soundness-of"

    def test_strips_latex_macros(self):
        assert slugify("The $\\Ga\\proves\\ph$ Relation") == "the-relation"

    def test_strips_existing_label(self):
        assert slugify("Validity {#sec-validity}") == "validity"


class TestOrderedListMarker:
    def test_digits_always_valid(self):
        assert is_ordered_list_marker("1")
        assert is_ordered_list_marker("23")

    def test_single_letter_valid(self):
        assert is_ordered_list_marker("a")
        assert is_ordered_list_marker("Z")

    def test_recognized_roman_numeral_valid(self):
        assert is_ordered_list_marker("iii")
        assert is_ordered_list_marker("xiv")

    def test_ordinary_word_rejected(self):
        # e.g. a sentence beginning "The. next sentence" must not be
        # mistaken for a list marker just because it ends in a period
        assert not is_ordered_list_marker("The")
        assert not is_ordered_list_marker("Kant")


class TestIsFenceLine:
    def test_code_fence(self):
        assert is_fence_line("```")

    def test_math_fence(self):
        assert is_fence_line("$$")

    def test_div_fence_open(self):
        assert is_fence_line(":::{.example}")

    def test_div_fence_close(self):
        assert is_fence_line(":::")

    def test_thematic_break(self):
        assert is_fence_line("---")
        assert is_fence_line("***")
        assert is_fence_line("- - -")

    def test_ordinary_text_not_a_fence(self):
        assert not is_fence_line("Some ordinary prose.")


class TestBlankGapContinuesList:
    def test_more_indented_continuation_continues(self):
        lines = ["", "   more indented text"]
        assert blank_gap_continues_list(lines, 1, base_indent=0)

    def test_sibling_item_at_same_indent_continues(self):
        lines = ["", "2. next item"]
        assert blank_gap_continues_list(lines, 1, base_indent=0)

    def test_ordinary_prose_at_margin_ends_list(self):
        lines = ["", "Back to ordinary prose."]
        assert not blank_gap_continues_list(lines, 1, base_indent=0)

    def test_fence_line_ends_list(self):
        lines = ["", ":::"]
        assert not blank_gap_continues_list(lines, 1, base_indent=0)

    def test_end_of_input_ends_list(self):
        assert not blank_gap_continues_list(["", ""], 2, base_indent=0)


class TestListItemRegex:
    def test_bare_digit_marker(self):
        m = LIST_ITEM_RE.match("1. Some text")
        assert m and m.group(3) == "1" and m.group(4) == "."

    def test_parenthesized_letter_marker(self):
        m = LIST_ITEM_RE.match("(a). Some text")
        assert m and m.group(2) == "(" and m.group(3) == "a"

    def test_bare_paren_marker(self):
        m = LIST_ITEM_RE.match("1) Some text")
        assert m and m.group(3) == "1" and m.group(4) == ")"


class TestFindHeadings:
    def test_finds_all_levels_by_default(self):
        text = "# Chapter {#sec-x .chapter}\n\n## Sub {#sec-x-sub}\n\n### Subsub\n"
        headings = find_headings(text)
        assert [h.level for h in headings] == [1, 2, 3]

    def test_level_filter(self):
        text = "# Chapter {#sec-x .chapter}\n\n## Sub {#sec-x-sub}\n\n### Subsub\n"
        headings = find_headings(text, level=2)
        assert len(headings) == 1
        assert headings[0].heading_text.startswith('Sub')

    def test_label_extracted(self):
        text = "## Validity {#sec-x-validity}\n"
        h = find_headings(text, level=2)[0]
        assert h.label == 'sec-x-validity'

    def test_label_none_when_absent(self):
        text = "## No Label\n"
        h = find_headings(text, level=2)[0]
        assert h.label is None

    def test_line_number_is_1_indexed(self):
        text = "text\n\n## Section {#sec-x}\n"
        h = find_headings(text, level=2)[0]
        assert h.line_number == 3

    def test_heading_text_left_raw_including_attrs(self):
        """find_headings deliberately doesn't strip the {...} block --
        that's each caller's own choice (see toc.py's _clean_title)."""
        text = "## References {.unnumbered}\n"
        h = find_headings(text, level=2)[0]
        assert h.heading_text == 'References {.unnumbered}'

    def test_decorative_heading_inside_div_excluded(self):
        text = (
            "## Real {#sec-x-real}\n\n"
            ":::{#thm-foo .theorem}\n## Transitivity\ncontent\n:::\n"
        )
        headings = find_headings(text, level=2)
        assert len(headings) == 1
        assert headings[0].label == 'sec-x-real'

    def test_heading_inside_code_fence_excluded(self):
        text = "## Real {#sec-x}\n\n```\n## not real\n```\n"
        headings = find_headings(text, level=2)
        assert len(headings) == 1
