"""
Cross-validation checks between course.yml and notes/.

These are the A/B/C/D checks run by `update` (step 3) before touching
course/ -- and exposed by `coursecraft validate --notes` for standalone
debugging. All four run together and return every problem at once, not
stopping at the first failure.

A: every notes_start/notes_end label used in any lecture exists in notes.
B: every exercise name in every assignment's exercises list has a .qmd file
   under notes/exercises/.
C: every exercise with show_solutions=True has a matching file under
   notes/solutions/ -- but only checked when notes/solutions/ actually exists
   (its absence is valid if the instructor isn't using solutions yet).
D: lectures' notes_end labels appear in non-decreasing document order
   (catches a notes_end typo'd to point earlier than an already-covered
   lecture, which check A alone can't detect since the label exists).
"""

from pathlib import Path
from typing import Union

from .schema import CourseConfig


def _all_toc_labels(toc_data: dict) -> set[str]:
    """Flat set of all labels appearing in toc_data (chapter labels and
    section labels, across chapters and appendices)."""
    labels: set[str] = set()
    for group in (toc_data.get("chapters", []), toc_data.get("appendices", [])):
        for chapter in group:
            if chapter.get("label"):
                labels.add(chapter["label"])
            for sec in chapter.get("sections", []):
                if sec.get("label"):
                    labels.add(sec["label"])
    return labels


def _label_positions(toc_data: dict) -> dict[str, int]:
    """Map every label in toc_data to its sequential position across the
    entire document tree (chapters first, then appendices; within each
    chapter, the chapter's own label before its sections)."""
    positions: dict[str, int] = {}
    pos = 0
    for group in (toc_data.get("chapters", []), toc_data.get("appendices", [])):
        for chapter in group:
            if chapter.get("label"):
                positions[chapter["label"]] = pos
                pos += 1
            for sec in chapter.get("sections", []):
                if sec.get("label"):
                    positions[sec["label"]] = pos
                    pos += 1
    return positions


def check_labels_exist(config: CourseConfig, toc_data: dict) -> list[str]:
    """Check A: every notes_start/notes_end label used in any lecture
    must exist as a real labeled heading in notes (as found by build_toc).
    Failure mode without this check: the frontier simply doesn't advance,
    and the instructor finds out when a student asks why new material
    isn't showing."""
    known = _all_toc_labels(toc_data)
    problems = []
    for i, lec in enumerate(config.lectures):
        name = config.lecture_name(i)
        if lec.notes_start is not None and lec.notes_start not in known:
            problems.append(
                f"{name}: notes_start {lec.notes_start!r} not found in notes"
            )
        if lec.notes_end not in known:
            problems.append(
                f"{name}: notes_end {lec.notes_end!r} not found in notes"
            )
    return problems


def check_exercises_exist(config: CourseConfig, notes_root: Union[str, Path]) -> list[str]:
    """Check B: every exercise name in every assignment's exercises list
    must have a matching .qmd file under notes/exercises/. Failure mode:
    a dangling {{< include >}} in a generated homework page, surfacing as
    a confusing Quarto error pointing at generated content, not the typo."""
    notes_root = Path(notes_root)
    exercises_dir = notes_root / "exercises"
    problems = []
    for a in config.assignments:
        for ex in a.exercises:
            if not (exercises_dir / f"{ex}.qmd").exists():
                problems.append(
                    f"'{a.name}': exercise {ex!r} not found in notes/exercises/"
                )
    return problems


def check_solutions_exist(config: CourseConfig, notes_root: Union[str, Path]) -> list[str]:
    """Check C: every exercise with show_solutions=True must have a matching
    file under notes/solutions/. Skipped entirely if notes/solutions/ doesn't
    exist -- its absence means the instructor simply hasn't populated solutions
    yet, which is a valid state (solutions aren't required to use coursecraft)."""
    notes_root = Path(notes_root)
    solutions_dir = notes_root / "solutions"
    if not solutions_dir.exists():
        return []
    problems = []
    for a in config.assignments:
        if not a.show_solutions:
            continue
        for ex in a.exercises:
            if not (solutions_dir / f"{ex}.qmd").exists():
                problems.append(
                    f"'{a.name}': no solution for {ex!r} in notes/solutions/ "
                    f"(required because show_solutions=true)"
                )
    return problems


def check_label_ordering(config: CourseConfig, toc_data: dict) -> list[str]:
    """Check D: each lecture's notes_end must appear at the same or a later
    position in the document than the previous lecture's notes_end. Catches a
    notes_end typo'd to point at content earlier in the book than an already-
    covered lecture -- which check A alone can't catch (the label exists, it's
    just the wrong one). Lectures whose notes_end isn't found in toc_data are
    skipped (check A already covers that case) without resetting the frontier,
    so subsequent lectures are still compared against the last valid position."""
    positions = _label_positions(toc_data)
    problems = []
    prev_pos = -1
    prev_name: str | None = None

    for i, lec in enumerate(config.lectures):
        name = config.lecture_name(i)
        end_label = lec.notes_end
        if end_label not in positions:
            continue  # A already flags this; don't cascade
        end_pos = positions[end_label]
        if prev_pos >= 0 and end_pos < prev_pos:
            problems.append(
                f"{name}: notes_end {end_label!r} (position {end_pos}) is before "
                f"{prev_name}'s notes_end (position {prev_pos})"
            )
        else:
            prev_pos = end_pos
            prev_name = name

    return problems


def run_course_checks(
    config: CourseConfig,
    notes_root: Union[str, Path],
    toc_data: dict,
) -> dict[str, list[str]]:
    """Run all four checks, returning a dict keyed by check name (including
    checks that found nothing, so a caller can report a clean summary)."""
    notes_root = Path(notes_root)
    return {
        "check_labels_exist": check_labels_exist(config, toc_data),
        "check_exercises_exist": check_exercises_exist(config, notes_root),
        "check_solutions_exist": check_solutions_exist(config, notes_root),
        "check_label_ordering": check_label_ordering(config, toc_data),
    }
