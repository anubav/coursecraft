"""
Profile generation for coursecraft update -- step 7.

A Quarto profile (_quarto-<date>.yml) is needed at every date where the
visible content set changes: every lecture date, every assignment assigned
date, and every assignment due date where show_solutions=True.

build_timeline() computes this sorted list of ProfileMoments from course.yml
alone (no toc data needed). generate_profiles() then uses toc_data to resolve
which sections are visible at each moment and writes the profile YAML files.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Union

import yaml

from .hw import assignment_stems
from .schema import CourseConfig, Lecture
from .toc import label_positions


@dataclass
class ProfileMoment:
    date: date
    lectures: list[Lecture]   # all lectures with date <= this date, in date order
    hw_files: list[str]       # hw/exam .qmd filenames active at this date,
                              # in assignment order (solutions replace prompts
                              # once show_solutions=True and due date has passed)


def build_timeline(config: CourseConfig) -> list[ProfileMoment]:
    """Return one ProfileMoment per unique event date, sorted ascending.

    Events: every lecture date, every assignment assigned date, and every
    assignment due date where show_solutions=True. Multiple events on the
    same date collapse into a single moment."""
    event_dates: set[date] = set()
    for lec in config.lectures:
        event_dates.add(lec.date)
    for a in config.assignments:
        event_dates.add(a.assigned)
        if a.show_solutions:
            event_dates.add(a.due)

    stems = assignment_stems(config)
    moments = []

    for d in sorted(event_dates):
        lectures = [lec for lec in config.lectures if lec.date <= d]

        hw_files = []
        for stem, assignment in zip(stems, config.assignments):
            if assignment.assigned > d:
                continue  # not yet assigned -- not in nav
            if assignment.show_solutions and assignment.due <= d:
                hw_files.append(f"{stem}-solutions.qmd")
            else:
                hw_files.append(f"{stem}.qmd")

        moments.append(ProfileMoment(date=d, lectures=lectures, hw_files=hw_files))

    return moments


def _visible_sections(moment: ProfileMoment, positions: dict[str, int]) -> set[str]:
    """Compute the set of section labels visible at this moment.

    For each lecture (in date order), the revealed range is:
    - cumulative: all positions 0..notes_end
    - windowed:   positions notes_start..notes_end only

    The result is the union across all lectures, so a later cumulative
    lecture fills any gaps left by earlier windowed ones."""
    visible: set[str] = set()
    for lec in moment.lectures:
        end_pos = positions.get(lec.notes_end, -1)
        if end_pos < 0:
            continue  # unknown label -- check A already flagged it
        if lec.effective_cumulative:
            visible.update(label for label, pos in positions.items() if pos <= end_pos)
        else:
            start_pos = positions.get(lec.notes_start, 0) if lec.notes_start else 0
            visible.update(
                label for label, pos in positions.items()
                if start_pos <= pos <= end_pos
            )
    return visible


def _sections_metadata(visible: set[str], toc_data: dict) -> dict[str, bool]:
    """Build the sections metadata dict in document order (chapters then
    appendices, chapter label before its own sections)."""
    result: dict[str, bool] = {}
    for group in (toc_data.get("chapters", []), toc_data.get("appendices", [])):
        for chapter in group:
            if chapter.get("label"):
                result[chapter["label"]] = chapter["label"] in visible
            for sec in chapter.get("sections", []):
                if sec.get("label"):
                    result[sec["label"]] = sec["label"] in visible
    return result


def _visible_chapters(
    visible: set[str], toc_data: dict
) -> tuple[list[str], list[str]]:
    """Return (chapter_paths, appendix_paths) for entries that have at
    least one label (chapter label or section label) in the visible set."""
    def has_visible(entry: dict) -> bool:
        if entry.get("label") in visible:
            return True
        return any(s.get("label") in visible for s in entry.get("sections", []))

    chapters = [e["path"] for e in toc_data.get("chapters", []) if has_visible(e)]
    appendices = [e["path"] for e in toc_data.get("appendices", []) if has_visible(e)]
    return chapters, appendices


def generate_profiles(
    config: CourseConfig,
    toc_data: dict,
    course_path: Union[str, Path],
) -> None:
    """Write one _quarto-<date>.yml profile file per timeline moment into
    course_path. Deletes stale profile files from a prior run first.

    Each profile lists only chapters/appendices with visible content (so
    Quarto never renders empty chapters). The base _quarto.yml in course/
    must have been stripped to chapters: [index.qmd] before calling this
    (done by _strip_quarto_chapter_lists in the update step), so the
    profile's chapters/appendices lists are appended to just index.qmd."""
    course_path = Path(course_path)

    for stale in course_path.glob("_quarto-*.yml"):
        stale.unlink()

    timeline = build_timeline(config)
    positions = label_positions(toc_data)

    for moment in timeline:
        visible = _visible_sections(moment, positions)
        vis_chapters, vis_appendices = _visible_chapters(visible, toc_data)
        sections = _sections_metadata(visible, toc_data)
        date_str = str(moment.date)

        profile: dict = {
            "project": {"output-dir": f"_book/{date_str}"},
            "book": {
                "chapters": vis_chapters + moment.hw_files,
                "appendices": vis_appendices,
            },
            "metadata": {"sections": sections},
        }

        path = course_path / f"_quarto-{date_str}.yml"
        path.write_text(yaml.dump(profile, sort_keys=False), encoding="utf-8")
