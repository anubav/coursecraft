"""
Instrumentation: wraps every labeled '##' section of a chapter or
appendix in a flat `:::{.content-hidden unless-meta="sections.<label>"}`
div. See ARCHITECTURE.md for why this is flat rather than nested (the
original hand-maintained version, one nested div per lecture boundary,
was unmaintainable) and why it wraps every labeled section
unconditionally rather than only ones course.yml happens to mention
(a lecture's cumulative frontier can pass through a section no lecture
ever names as its own boundary).

Deliberately course.yml-independent: this is a pure function of the
notes content alone. Which sections.* keys end up true or false for a
given profile is decided later, during profile generation -- this
module only makes sure every section has a hook to hang that decision
on.
"""

from .structure import find_headings


def instrument(text: str) -> str:
    lines = text.split('\n')

    # every structural heading, any level -- needed to find where a
    # labeled section's content actually ends
    all_headings = find_headings(text)

    # just the labeled '##' headings -- these are what get wrapped.
    # An unlabeled '##' is silently left alone here; catching that is
    # lint's job, not instrument's.
    labeled_sections = [
        (h.line_number - 1, h.level, h.label)
        for h in all_headings
        if h.level == 2 and h.label is not None
    ]

    def section_end(start_idx: int, level: int) -> int:
        for h in all_headings:
            i = h.line_number - 1
            if i > start_idx and h.level <= level:
                return i
        return len(lines)

    inserts_before: dict[int, list[str]] = {}
    inserts_after: dict[int, list[str]] = {}
    for start_idx, level, label in labeled_sections:
        end_idx = section_end(start_idx, level)
        inserts_before.setdefault(start_idx, []).append(
            f'::: {{.content-hidden unless-meta="sections.{label}"}}'
        )
        inserts_after.setdefault(end_idx, []).append(':::')

    out = []
    for i, line in enumerate(lines):
        if i in inserts_after:
            out.extend(inserts_after[i])
        if i in inserts_before:
            out.extend(inserts_before[i])
        out.append(line)
    if len(lines) in inserts_after:
        out.extend(inserts_after[len(lines)])

    return '\n'.join(out)
