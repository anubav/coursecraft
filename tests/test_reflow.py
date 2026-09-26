from coursecraft.reflow import reflow, _split_sentences, _fix_dangerous_line_starts


class TestLproofProtection:
    """.lproof content must survive byte-for-byte, regardless of what
    individual lines inside it look like."""

    def test_lproof_block_untouched_including_trailing_whitespace(self):
        text = (
            ":::{.lproof}\n"
            "    1. 2 > 0                    [Arithmetic]   \n"
            "    2. y > 1                    [Premise]\n"
            ":::\n"
        )
        assert reflow(text, width=None) == text

    def test_lproof_survives_even_with_non_numbered_continuation_line(self):
        """Regression: protection originally only worked by coincidence,
        because every real proof line happened to start with a digit.
        A non-numbered line must be protected too."""
        text = (
            ":::{.lproof}\n"
            "    1. some step\n"
            "       a continuation line with no leading number\n"
            ":::\n"
        )
        assert reflow(text, width=None) == text

    def test_lproof_closing_fence_not_swallowed_by_list_reflow(self):
        """Regression: an .lproof div's closing ::: at the same
        indentation as a preceding ordinary numbered list was once
        mistaken for list continuation text, corrupting div structure."""
        text = (
            ":::{.exercise}\n"
            "1. Do the thing.\n"
            "\n"
            ":::{.lproof}\n"
            "    1. step one\n"
            ":::\n"
            ":::\n"
        )
        result = reflow(text, width=None)
        assert result.count(":::{.lproof}") == 1
        assert "    1. step one" in result
        # both the lproof-closing ::: and the exercise-closing ::: must
        # still be present as real fence lines, not merged into prose
        assert result.rstrip().endswith(":::\n:::" ) or result.rstrip().endswith(":::\n:::".strip())


class TestThematicBreak:
    """Regression: a bare '---' merged into a paragraph gets converted
    by Pandoc's smart-typography into a literal em dash instead of
    staying a horizontal rule."""

    def test_thematic_break_stays_on_its_own_line(self):
        text = "This completes the proof.\n---\n"
        result = reflow(text, width=None)
        lines = [l for l in result.split("\n") if l.strip()]
        assert "---" in lines
        assert lines[0] != "This completes the proof. ---"

    def test_thematic_break_not_absorbed_after_blank_line(self):
        text = "Some paragraph.\n\n***\n\nMore text.\n"
        result = reflow(text, width=None)
        assert "***" in result.split("\n")


class TestDangerousLineStarts:
    """Regression: a wrapped/split line starting with something that
    looks like a list marker (a bare year, a Pandoc example-list ref)
    gets misparsed by Pandoc as starting a brand-new list, mid-sentence."""

    def test_bare_year_not_left_at_start_of_line(self):
        lines = ["Some text ending with a citation to", "1975. Kant said this."]
        fixed = _fix_dangerous_line_starts(lines)
        assert not fixed[1].startswith("1975.")
        assert "1975." in fixed[0]

    def test_example_list_ref_not_left_at_start_of_line(self):
        lines = ["See the model", "@fig-model-S) for details."]
        fixed = _fix_dangerous_line_starts(lines)
        assert not fixed[1].startswith("@fig-model-S)")

    def test_safe_line_starts_unchanged(self):
        lines = ["First line.", "Second line starts normally."]
        assert _fix_dangerous_line_starts(lines) == lines


class TestSentenceSplitting:
    def test_basic_split(self):
        chunks = _split_sentences("First sentence. Second sentence.")
        assert chunks == ["First sentence.", "Second sentence."]

    def test_abbreviation_not_split(self):
        chunks = _split_sentences("Dr. Smith agrees with this.")
        assert len(chunks) == 1

    def test_eg_abbreviation_not_split(self):
        chunks = _split_sentences("This holds, e.g. in this case. Next sentence.")
        assert len(chunks) == 2
        assert "e.g." in chunks[0]

    def test_decimal_number_not_split(self):
        chunks = _split_sentences("The value is 3.14 exactly. Next sentence.")
        assert len(chunks) == 2
        assert "3.14" in chunks[0]

    def test_parenthesized_marker_not_mistaken_for_sentence_end(self):
        """Regression: '(a).' was treated as a sentence boundary,
        splitting a list marker from its own content."""
        text = "(a). Construct a model such that it holds."
        result = reflow(text, width=None)
        assert result.strip() == "(a). Construct a model such that it holds."

    def test_math_span_period_not_split(self):
        chunks = _split_sentences("Consider $f(x) = 1.5$ here. Next sentence.")
        assert len(chunks) == 2


class TestOrderedListReflow:
    def test_simple_hanging_indent(self):
        text = (
            "1. First item that is long enough to need wrapping across "
            "more than a single line in the output.\n"
            "2. Second item.\n"
        )
        result = reflow(text, width=None)
        lines = result.split("\n")
        assert lines[0].startswith("1. ")
        # continuation lines (if any) should be indented to align under "1. "
        for l in lines[1:]:
            if l and not l.startswith("2."):
                assert l.startswith("   ")

    def test_nested_roman_numeral_sublist(self):
        text = (
            "a. Top level item.\n"
            "    i. Nested item one.\n"
            "    ii. Nested item two.\n"
        )
        result = reflow(text, width=None)
        assert "i. Nested item one." in result
        assert "ii. Nested item two." in result

    def test_list_ends_at_ordinary_prose(self):
        text = "1. An item.\n\nBack to ordinary prose.\n"
        result = reflow(text, width=None)
        assert result.strip().endswith("Back to ordinary prose.")
        assert not result.strip().endswith("prose.\n   ")  # not hanging-indented


class TestFootnoteContinuation:
    def test_indented_continuation_paragraph_preserved(self):
        """Regression: a footnote's second paragraph, indented 4 spaces
        per Pandoc's requirement, had its indentation stripped by
        reflow, silently detaching it from the footnote."""
        text = (
            "Some text.[^note]\n"
            "\n"
            "[^note]: First line of the footnote.\n"
            "\n"
            "    Second paragraph of the same footnote, indented.\n"
        )
        result = reflow(text, width=None)
        assert "\n    Second paragraph of the same footnote, indented.\n" in result


class TestColumnWrapMode:
    def test_width_wraps_at_column(self):
        text = "word " * 30
        result = reflow(text.strip() + "\n", width=40)
        for line in result.strip().split("\n"):
            assert len(line) <= 45  # some slack for the dangerous-start guard

    def test_none_width_is_semantic_mode(self):
        text = "First sentence. Second sentence.\n"
        result = reflow(text, width=None)
        assert result.strip() == "First sentence.\nSecond sentence."


class TestIdempotency:
    def test_reflow_twice_is_stable(self):
        text = (
            "Some intro. It has multiple sentences, e.g. this one.\n\n"
            "1. First item with a fairly long sentence to force wrapping "
            "behavior across lines.\n"
            "2. Short item.\n"
        )
        once = reflow(text, width=None)
        twice = reflow(once, width=None)
        assert once == twice

    def test_column_wrap_idempotent(self):
        text = "A reasonably long paragraph of prose. " * 5 + "\n"
        once = reflow(text, width=80)
        twice = reflow(once, width=80)
        assert once == twice


class TestFrontmatterUntouched:
    def test_yaml_frontmatter_passed_through(self):
        text = (
            "---\n"
            "bibliography: \"foo.bib\"\n"
            "number-sections: true\n"
            "---\n\n"
            "Some prose. Another sentence.\n"
        )
        result = reflow(text, width=None)
        assert result.startswith(
            "---\nbibliography: \"foo.bib\"\nnumber-sections: true\n---\n"
        )
