"""
Cross-validation checks between course.yml and notes/.

These are the A/B/C checks run by `update` (step 3) before touching
course/ -- and exposed by `coursecraft validate --notes` for standalone
debugging. All three run together and return every problem at once, not
stopping at the first failure.

A: every label in any lecture's sections list exists in notes.
B: every exercise name in every assignment's exercises list has a .qmd file
   under notes/exercises/.
C: every exercise with show_solutions=True has a matching file under
   notes/solutions/ -- but only checked when notes/solutions/ actually exists
   (its absence is valid if the instructor isn't using solutions yet).
"""

from pathlib import Path

from .schema import CourseConfig
from .toc import label_positions


def check_labels_exist(config: CourseConfig, toc_data: dict) -> list[str]:
    """Check A: every label in any lecture's sections list must exist as a
    real labeled heading in notes (as found by build_toc). Chapter-level
    labels are valid (they auto-expand to all subsections in profiles).
    Failure mode without this check: the section simply isn't shown, and
    the instructor finds out when students report missing content."""
    known = set(label_positions(toc_data).keys())
    problems = []
    for i, lec in enumerate(config.lectures):
        name = config.lecture_name(i)
        for label in lec.sections:
            if label not in known:
                problems.append(
                    f"{name}: sections label {label!r} not found in notes"
                )
    return problems


def check_exercises_exist(config: CourseConfig, notes_root: str | Path) -> list[str]:
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


def check_solutions_exist(config: CourseConfig, notes_root: str | Path) -> list[str]:
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


def run_course_checks(
    config: CourseConfig,
    notes_root: str | Path,
    toc_data: dict,
) -> dict[str, list[str]]:
    """Run all three checks, returning a dict keyed by check name (including
    checks that found nothing, so a caller can report a clean summary)."""
    notes_root = Path(notes_root)
    return {
        "check_labels_exist": check_labels_exist(config, toc_data),
        "check_exercises_exist": check_exercises_exist(config, notes_root),
        "check_solutions_exist": check_solutions_exist(config, notes_root),
    }
