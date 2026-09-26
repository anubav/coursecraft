"""
course.yaml schema.

This is the single, authoritative definition of what a valid
course.yaml looks like -- anything that produces or consumes one
(the CLI today, a future web UI eventually) should import CourseConfig
from here rather than re-implementing validation.
"""

from datetime import date
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator


def _validate_label(value: str, field_name: str) -> str:
    if not value.startswith("sec-"):
        raise ValueError(
            f"{field_name} should be a section label starting with "
            f"'sec-' (got {value!r})."
        )
    return value


class CourseInfo(BaseModel):
    title: str
    notes_repo: str
    # which branch of notes_repo this section is built from -- None
    # means the repo's own default branch (typically main). Lets an
    # instructor build off a personal long-lived branch of the notes
    # repo instead of main, without ever needing to merge it back.
    notes_branch: Optional[str] = None
    solutions_repo: Optional[str] = None


class SectionInfo(BaseModel):
    instructor: str
    course_number: str
    term: str
    location: str
    meeting_times: str
    start_date: date
    end_date: date
    description: str = ""

    @model_validator(mode="after")
    def _check_dates(self) -> "SectionInfo":
        if self.end_date <= self.start_date:
            raise ValueError(
                f"end_date ({self.end_date}) must be after "
                f"start_date ({self.start_date})"
            )
        return self


class Lecture(BaseModel):
    date: date
    name: Optional[str] = None
    notes_start: Optional[str] = None
    notes_end: str
    # None = context-dependent default (see effective_cumulative below),
    # not "unset -> False". A lecture that just continues from the
    # frontier defaults to cumulative; an explicit notes_start signals a
    # deliberately scoped view (e.g. a review lecture) and defaults to
    # windowed. Either can be overridden explicitly with this field.
    cumulative: Optional[bool] = None

    @model_validator(mode="after")
    def _check_labels(self) -> "Lecture":
        if self.notes_start is not None:
            _validate_label(self.notes_start, "notes_start")
        _validate_label(self.notes_end, "notes_end")
        return self

    @property
    def effective_cumulative(self) -> bool:
        if self.cumulative is not None:
            return self.cumulative
        return self.notes_start is None


class Assignment(BaseModel):
    name: str
    assigned: date
    due: date
    exercises: list[str] = Field(default_factory=list)
    # due is the one and only solutions-reveal date, when solutions are
    # shown at all -- no separate solutions_start/end. Once revealed,
    # solutions stay visible for the rest of the course, same as
    # everything else in this system; nothing here ever un-reveals.
    show_solutions: bool = False
    is_exam: bool = False

    @model_validator(mode="after")
    def _check_dates(self) -> "Assignment":
        if self.due < self.assigned:
            raise ValueError(
                f"'{self.name}': due ({self.due}) is before "
                f"assigned ({self.assigned})"
            )
        return self

    @model_validator(mode="after")
    def _check_exercise_names(self) -> "Assignment":
        for ex in self.exercises:
            if "/" in ex or ex.endswith(".qmd"):
                raise ValueError(
                    f"'{self.name}': exercise {ex!r} should be a bare "
                    f"name (e.g. 'expressions'), not a path or filename."
                )
        return self


class _CourseSectionOnly(BaseModel):
    """Private helper for CourseConfig.load_course_info -- deliberately
    just the `course:` block. Extra top-level keys (section/lectures/
    assignments) are silently ignored, not errors: neither CourseInfo
    nor this wrapper sets extra="forbid", so validating this smaller
    model against a full course.yaml dict only checks what it
    declares and never touches the rest."""
    course: CourseInfo


class CourseConfig(BaseModel):
    course: CourseInfo
    section: SectionInfo
    lectures: list[Lecture] = Field(default_factory=list)
    assignments: list[Assignment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_lectures(self) -> "CourseConfig":
        dates = [lec.date for lec in self.lectures]
        if len(dates) != len(set(dates)):
            raise ValueError("Two lectures cannot share the same date")
        self.lectures.sort(key=lambda lec: lec.date)
        return self

    @model_validator(mode="after")
    def _check_assignment_names(self) -> "CourseConfig":
        names = [a.name for a in self.assignments]
        if len(names) != len(set(names)):
            raise ValueError("Assignment names must be unique")
        return self

    @model_validator(mode="after")
    def _check_dates_within_term(self) -> "CourseConfig":
        lo, hi = self.section.start_date, self.section.end_date
        errors = []
        for lec in self.lectures:
            if not (lo <= lec.date <= hi):
                errors.append(
                    f"lecture on {lec.date} falls outside the "
                    f"section's {lo}..{hi} range"
                )
        for a in self.assignments:
            for d, label in [(a.assigned, "assigned"), (a.due, "due")]:
                if not (lo <= d <= hi):
                    errors.append(
                        f"'{a.name}' {label} date {d} falls outside "
                        f"the section's {lo}..{hi} range"
                    )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def lecture_name(self, index: int) -> str:
        """Effective name for the lecture at position `index` (0-indexed,
        into the already date-sorted `lectures` list): 'lecture-01',
        etc., unless an explicit name was given."""
        lec = self.lectures[index]
        return lec.name or f"lecture-{index + 1:02d}"

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CourseConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(raw)

    @classmethod
    def load_course_info(cls, path: str | Path) -> CourseInfo:
        """Partial parse: validates only the top-level `course:` block
        (title/notes_repo/notes_branch/solutions_repo), ignoring
        section/lectures/assignments entirely -- because they're
        allowed not to exist yet. fetch-notes needs to know where the
        notes repo is, and runs before the rest of course.yaml is
        necessarily filled in (right after `init` scaffolds it with
        REPLACE_ME everywhere else, before the course.yaml-filling
        wizard has had a chance to run)."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return _CourseSectionOnly.model_validate(raw).course
