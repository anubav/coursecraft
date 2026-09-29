"""
coursecraft.yml schema -- the portability manifest a notes repo (like
logic-notes) declares, telling coursecraft how to interpret its
structure. Kept separate from schema.py deliberately: course.yml
describes one section's schedule and is different for every section;
this describes the shape of the master content itself, and is the
same for every section built from a given notes repo. See
ARCHITECTURE.md for the full rationale.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

SUPPORTED_SPEC_VERSIONS = {"1.0"}


class Conventions(BaseModel):
    chapter_glob: str
    appendix_dir_glob: str
    exercise_glob: str
    insert_glob: str
    label_prefix: str = "sec-"
    chapter_marker_class: str = "chapter"
    macros_include: str | None = None
    raw_text_div_classes: list[str] = Field(default_factory=lambda: ["lproof"])

    # catches a typo'd field name (e.g. 'exercize_glob') immediately,
    # instead of it being silently ignored and coursecraft falling back
    # to a default deep inside some later, harder-to-diagnose step
    model_config = {"extra": "forbid"}


class NotesManifest(BaseModel):
    coursecraft_spec: str
    conventions: Conventions

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check_spec_version(self) -> "NotesManifest":
        if self.coursecraft_spec not in SUPPORTED_SPEC_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_SPEC_VERSIONS))
            raise ValueError(
                f"coursecraft_spec {self.coursecraft_spec!r} is not "
                f"supported (supports: {supported})."
            )
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "NotesManifest":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(raw)
