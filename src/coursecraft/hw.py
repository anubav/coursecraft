"""Generate homework and exam .qmd files in course/ from course.yml."""

from pathlib import Path
from typing import Optional

from .schema import Assignment, CourseConfig


def _include(path: str) -> str:
    return "{{< include " + path + " >}}"


def _due_str(assignment: Assignment) -> str:
    d = assignment.due
    return d.strftime("%B") + f" {d.day}, {d.year}"


def _hw_content(
    assignment: Assignment, macros_include: Optional[str] = None
) -> str:
    lines = [f"# {assignment.name} {{.unnumbered}}", ""]
    if macros_include:
        lines += [_include(macros_include), ""]
    lines += [f"**Due: {_due_str(assignment)}**"]
    for ex in assignment.exercises:
        lines += ["", f"@exr-{ex}", "", _include(f"/exercises/{ex}.qmd")]
    lines.append("")
    return "\n".join(lines)


def _solutions_content(
    assignment: Assignment, macros_include: Optional[str] = None
) -> str:
    lines = [f"# {assignment.name} (with solutions) {{.unnumbered}}", ""]
    if macros_include:
        lines += [_include(macros_include), ""]
    for ex in assignment.exercises:
        lines += [
            "",
            f"@exr-{ex}",
            "",
            _include(f"/exercises/{ex}.qmd"),
            "",
            "**Solution:**",
            "",
            _include(f"/solutions/{ex}.qmd"),
        ]
    lines.append("")
    return "\n".join(lines)


def assignment_stems(config: CourseConfig) -> list[str]:
    """Return the hw-NN / exam-NN filename stem for each assignment in
    config.assignments order. Shared by generate_homework_files and the
    profile generator so both use the same numbering."""
    hw_n = exam_n = 0
    stems = []
    for a in config.assignments:
        if a.is_exam:
            exam_n += 1
            stems.append(f"exam-{exam_n:02d}")
        else:
            hw_n += 1
            stems.append(f"hw-{hw_n:02d}")
    return stems


def generate_homework_files(
    config: CourseConfig,
    course_path: Path,
    macros_include: Optional[str] = None,
) -> None:
    """Write hw-NN.qmd / exam-NN.qmd (and *-solutions.qmd when
    show_solutions=True) into course_path. Deletes any stale hw-* /
    exam-* files from a prior run first so removed assignments leave
    no orphans."""
    for pattern in ("hw-*.qmd", "exam-*.qmd"):
        for stale in course_path.glob(pattern):
            stale.unlink()

    for stem, assignment in zip(assignment_stems(config), config.assignments):
        (course_path / f"{stem}.qmd").write_text(
            _hw_content(assignment, macros_include), encoding="utf-8"
        )
        if assignment.show_solutions:
            (course_path / f"{stem}-solutions.qmd").write_text(
                _solutions_content(assignment, macros_include), encoding="utf-8"
            )
