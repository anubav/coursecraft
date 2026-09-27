"""
Lint checks for .qmd files.

Unlike reflow.py, nothing here rewrites a file. A missing section label
is reported, not auto-generated: the label is a persistent identifier
other content may eventually cross-reference, and choosing its name is
a decision for whoever writes the heading, not something to script.
"""

from dataclasses import dataclass

from .structure import find_headings


@dataclass
class UnlabeledHeading:
    line_number: int  # 1-indexed
    heading_text: str


def find_unlabeled_sections(text: str) -> list[UnlabeledHeading]:
    """Return every top-level (fence-depth 0) '##' heading that lacks a
    {#...} label. A heading inside a .theorem/.example/etc. div (e.g. a
    decorative title inside an lproof-adjacent environment) is not real
    document structure and is correctly never flagged, since it's below
    structural top level."""
    return [
        UnlabeledHeading(line_number=h.line_number, heading_text=h.heading_text)
        for h in find_headings(text, level=2)
        if h.label is None
    ]
