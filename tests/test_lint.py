from coursecraft.lint import find_unlabeled_sections


class TestFindUnlabeledSections:
    def test_labeled_heading_not_flagged(self):
        text = "## Introduction {#sec-ch1-introduction}\n\nSome text.\n"
        assert find_unlabeled_sections(text) == []

    def test_unlabeled_heading_flagged(self):
        text = "## Introduction\n\nSome text.\n"
        violations = find_unlabeled_sections(text)
        assert len(violations) == 1
        assert violations[0].heading_text == "Introduction"
        assert violations[0].line_number == 1

    def test_chapter_level_heading_never_flagged(self):
        """A '#' (chapter title) heading is a different concern,
        handled separately -- lint only checks '##' subsections."""
        text = "# Chapter One\n\n## Missing Label\n"
        violations = find_unlabeled_sections(text)
        assert len(violations) == 1
        assert violations[0].heading_text == "Missing Label"

    def test_heading_inside_theorem_div_not_flagged(self):
        """A decorative title heading inside a .theorem/.example div is
        not real document structure and must never be flagged."""
        text = (
            "## Real Section {#sec-ch1-real}\n\n"
            ":::{#thm-foo .theorem}\n"
            "## Transitivity\n"
            "Some theorem content.\n"
            ":::\n"
        )
        assert find_unlabeled_sections(text) == []

    def test_multiple_unlabeled_headings_all_reported(self):
        text = "## First\n\ntext\n\n## Second\n\nmore text\n"
        violations = find_unlabeled_sections(text)
        assert len(violations) == 2
        assert [v.heading_text for v in violations] == ["First", "Second"]

    def test_heading_inside_code_fence_not_flagged(self):
        text = "```\n## not a real heading\n```\n"
        assert find_unlabeled_sections(text) == []
