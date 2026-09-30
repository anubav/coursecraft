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

import yaml

from .hw import assignment_stems
from .schema import CourseConfig, Lecture


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


def _expand_labels(sections: list[str], toc_data: dict) -> set[str]:
    """Expand chapter labels to all their subsections; leave subsection labels as-is."""
    children: dict[str, set[str]] = {}
    for group in (toc_data.get("chapters", []), toc_data.get("appendices", [])):
        for entry in group:
            top_label = entry.get("label")
            if top_label:
                child_set = {top_label}
                for sec in entry.get("sections", []):
                    if sec.get("label"):
                        child_set.add(sec["label"])
                children[top_label] = child_set
    expanded: set[str] = set()
    for label in sections:
        if label in children:
            expanded.update(children[label])
        else:
            expanded.add(label)
    return expanded


def _visible_sections(moment: ProfileMoment, toc_data: dict) -> set[str]:
    """Compute the set of section labels visible at this moment.

    Cumulative lectures add their sections to the running frontier.
    A windowed lecture at the moment's own date short-circuits and returns
    only its own sections (the frontier is ignored for that date)."""
    frontier: set[str] = set()
    for lec in moment.lectures:
        if lec.cumulative:
            frontier |= _expand_labels(lec.sections, toc_data)
    if moment.lectures:
        last_lec = moment.lectures[-1]
        if last_lec.date == moment.date and not last_lec.cumulative:
            return _expand_labels(last_lec.sections, toc_data)
    return frontier


def _sections_metadata(visible: set[str], toc_data: dict) -> dict[str, bool]:
    """Build the sections metadata dict in document order (chapters then
    appendices, chapter label before its own sections).

    A chapter label is set to true when the chapter label itself OR any of
    its subsection labels are in the visible set -- so the chapter heading
    is never hidden when content from that chapter is being shown."""
    result: dict[str, bool] = {}
    for group in (toc_data.get("chapters", []), toc_data.get("appendices", [])):
        for chapter in group:
            ch_label = chapter.get("label")
            sec_labels = [s.get("label") for s in chapter.get("sections", []) if s.get("label")]
            if ch_label:
                result[ch_label] = ch_label in visible or any(s in visible for s in sec_labels)
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
    course_path: str | Path,
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

    for moment in timeline:
        visible = _visible_sections(moment, toc_data)
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
