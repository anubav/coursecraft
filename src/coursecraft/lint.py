"""
Lint checks for .qmd files.

Unlike reflow.py, nothing here rewrites a file. A missing section label
is reported, not auto-generated: the label is a persistent identifier
other content may eventually cross-reference, and choosing its name is
a decision for whoever writes the heading, not something to script.
"""

from dataclasses import dataclass

from .structure import FenceTracker, HEADING_RE, LABEL_RE


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
    violations = []
    tracker = FenceTracker()
    for i, line in enumerate(text.split('\n')):
        is_fence = tracker.consume(line)
        if not is_fence and tracker.at_structural_top_level():
            m = HEADING_RE.match(line)
            if m and len(m.group(1)) == 2 and not LABEL_RE.search(line):
                violations.append(UnlabeledHeading(
                    line_number=i + 1,
                    heading_text=m.group(2).strip(),
                ))
    return violations
