from coursecraft.instrument import instrument


class TestBasicWrapping:
    def test_single_labeled_section_wrapped(self):
        text = (
            "# Chapter One {#sec-one .chapter}\n\n"
            "## Intro {#sec-one-intro}\n\n"
            "Some text.\n"
        )
        result = instrument(text)
        lines = result.split('\n')
        assert lines[2] == '::: {.content-hidden unless-meta="sections.sec-one-intro"}'
        assert result.rstrip().endswith(':::')

    def test_chapter_heading_never_wrapped(self):
        """Only '##' gets wrapped -- chapter-level '#' visibility is
        controlled by which FILE is in a profile's chapters: list, not
        by a div around the chapter heading."""
        text = "# Chapter One {#sec-one .chapter}\n\nSome text.\n"
        assert instrument(text) == text

    def test_unlabeled_heading_left_alone(self):
        """Not this function's job to catch -- lint does that."""
        text = "# Chapter {#sec-x .chapter}\n\n## No Label Here\n\ntext\n"
        result = instrument(text)
        assert 'content-hidden' not in result
        assert result == text

    def test_multiple_sections_wrapped_flat_not_nested(self):
        text = (
            "# Chapter {#sec-x .chapter}\n\n"
            "## First {#sec-x-first}\n\ntext one\n\n"
            "## Second {#sec-x-second}\n\ntext two\n"
        )
        result = instrument(text)
        assert result.count('::: {.content-hidden unless-meta="sections.sec-x-first"}') == 1
        assert result.count('::: {.content-hidden unless-meta="sections.sec-x-second"}') == 1
        # flat: never more than one open unless-meta div before a close
        depth = 0
        for line in result.split('\n'):
            if line.startswith('::: {.content-hidden'):
                depth += 1
                assert depth == 1, "sections must not nest"
            elif line.strip() == ':::':
                depth -= 1

    def test_last_section_closes_at_end_of_file(self):
        text = "# Chapter {#sec-x .chapter}\n\n## Only {#sec-x-only}\n\ntext\n"
        result = instrument(text)
        assert result.rstrip().split('\n')[-1] == ':::'


class TestFenceAwareness:
    def test_heading_inside_theorem_div_not_mistaken_for_section(self):
        """A decorative '##' title inside a .theorem div (lproof's own
        convention) must never be treated as a real section boundary."""
        text = (
            "# Chapter {#sec-x .chapter}\n\n"
            "## Real Section {#sec-x-real}\n\n"
            ":::{#thm-foo .theorem}\n"
            "## Transitivity\n"
            "Some theorem content.\n"
            ":::\n\n"
            "More prose after the theorem.\n"
        )
        result = instrument(text)
        assert result.count('content-hidden') == 1  # only the real section
        assert '## Transitivity' in result  # untouched, not wrapped
        # the real section's wrap must extend past the nested theorem div,
        # not close early right before it
        lines = result.split('\n')
        close_idx = [i for i, l in enumerate(lines) if l.strip() == ':::'][-1]
        assert 'More prose after the theorem.' in lines[:close_idx + 1]

    def test_lproof_block_byte_identical_even_when_wrapped(self):
        text = (
            "# Chapter {#sec-x .chapter}\n\n"
            "## Proof Section {#sec-x-proof}\n\n"
            ":::{.lproof}\n"
            "    1. step one                    [Premise]\n"
            "    2. step two                    [R1: 1]\n"
            ":::\n"
        )
        result = instrument(text)
        assert "    1. step one                    [Premise]\n" \
               "    2. step two                    [R1: 1]" in result

    def test_code_fence_headings_ignored(self):
        text = (
            "# Chapter {#sec-x .chapter}\n\n"
            "## Real {#sec-x-real}\n\n"
            "```\n## not a real heading\n```\n"
        )
        result = instrument(text)
        assert result.count('content-hidden') == 1


class TestSectionBoundaries:
    def test_section_ends_at_next_same_level_heading(self):
        text = (
            "# Chapter {#sec-x .chapter}\n\n"
            "## First {#sec-x-first}\n\n"
            "### Subsection\n\ntext\n\n"
            "## Second {#sec-x-second}\n\ntext\n"
        )
        result = instrument(text)
        lines = result.split('\n')
        first_close = None
        for i, l in enumerate(lines):
            if l.strip() == ':::' and first_close is None:
                first_close = i
        # the ### Subsection must be captured WITHIN the first wrap,
        # since it's a deeper heading level than the section boundary
        assert '### Subsection' in '\n'.join(lines[:first_close])

    def test_nested_subheading_does_not_end_section_early(self):
        text = (
            "# Chapter {#sec-x .chapter}\n\n"
            "## Outer {#sec-x-outer}\n\n"
            "### Inner\n\ninner text\n\n"
            "text after inner still in outer section\n"
        )
        result = instrument(text)
        assert result.count('content-hidden') == 1
        assert 'text after inner still in outer section' in result
        # confirm that text is BEFORE the closing :::
        lines = result.split('\n')
        close_idx = lines.index(':::')
        assert any('text after inner' in l for l in lines[:close_idx])
