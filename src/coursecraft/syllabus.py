"""Generate course/index.qmd (the syllabus) -- step 8 of the update flow."""

from datetime import date
from pathlib import Path

from .schema import CourseConfig, Lecture


def _short_date(d: date) -> str:
    """'Sep 28' -- abbreviated month, no leading zero on day."""
    return d.strftime("%b") + f" {d.day}"


def _label_titles(toc_data: dict) -> dict[str, str]:
    """Map every label in toc_data to its display title."""
    titles: dict[str, str] = {}
    for group in (toc_data.get("chapters", []), toc_data.get("appendices", [])):
        for chapter in group:
            if chapter.get("label"):
                titles[chapter["label"]] = chapter["title"]
            for sec in chapter.get("sections", []):
                if sec.get("label"):
                    titles[sec["label"]] = sec["title"]
    return titles


def _label_chapter(toc_data: dict) -> dict[str, tuple[str, str]]:
    """Map every label to (chapter_label, chapter_title) of the chapter
    it belongs to. Chapter labels map to themselves."""
    result: dict[str, tuple[str, str]] = {}
    for group in (toc_data.get("chapters", []), toc_data.get("appendices", [])):
        for chapter in group:
            ch_label = chapter.get("label", "")
            ch_title = chapter.get("title", "")
            if ch_label:
                result[ch_label] = (ch_label, ch_title)
            for sec in chapter.get("sections", []):
                if sec.get("label"):
                    result[sec["label"]] = (ch_label, ch_title)
    return result


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a left-aligned Markdown table."""
    col_count = len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _ in range(col_count)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _schedule_parts(config: CourseConfig, toc_data: dict) -> list[str]:
    """Build the '## Schedule' section, grouping lectures by chapter with
    a '### Chapter Title' subheading whenever the chapter changes."""
    if not config.lectures:
        return []

    titles = _label_titles(toc_data)
    ch_map = _label_chapter(toc_data)

    chapter_labels = {
        ch.get("label")
        for group in (toc_data.get("chapters", []), toc_data.get("appendices", []))
        for ch in group
        if ch.get("label")
    }

    lecture_items: list[tuple[Lecture, str, str]] = []
    # (lec, start_title, chapter_title)

    for lec in config.lectures:
        first_label = lec.sections[0] if lec.sections else None
        if lec.name:
            start_title = lec.name
        elif first_label is None:
            start_title = "—"
        elif first_label in chapter_labels:
            start_title = "Introduction"
        else:
            start_title = titles.get(first_label, first_label)
        _, ch_title = ch_map.get(first_label, ("", "")) if first_label else ("", "")
        lecture_items.append((lec, start_title, ch_title))

    parts: list[str] = ["", "## Schedule"]
    current_chapter = None
    chapter_rows: list[list[str]] = []

    def _flush(ch_title: str) -> None:
        if chapter_rows:
            parts.append("")
            if ch_title:
                parts.append(f"### {ch_title}")
                parts.append("")
            parts.append(_md_table(["Date", "Topic"], chapter_rows))
            chapter_rows.clear()

    for lec, start_title, ch_title in lecture_items:
        if ch_title != current_chapter:
            _flush(current_chapter or "")
            current_chapter = ch_title
        chapter_rows.append([_short_date(lec.date), start_title])

    _flush(current_chapter or "")
    return parts


def _build_syllabus(config: CourseConfig, toc_data: dict) -> str:
    sec = config.section
    info_rows = [
        ["**Course**", f"{sec.course_number}: {config.course.title}"],
        ["**Term**", sec.term],
        ["**Instructor**", sec.instructor],
        ["**Location**", sec.location],
        ["**Meeting times**", sec.meeting_times],
    ]

    parts = [
        "# Syllabus {.unnumbered}",
        "",
        _md_table(["", ""], info_rows),
    ]

    if sec.description:
        parts += ["", sec.description]

    parts += _schedule_parts(config, toc_data)

    if config.assignments:
        assignment_rows = [
            [a.name, _short_date(a.assigned), _short_date(a.due)]
            for a in config.assignments
        ]
        parts += [
            "",
            "## Assignments",
            "",
            _md_table(["", "Assigned", "Due"], assignment_rows),
        ]

    parts.append("")
    return "\n".join(parts)


def generate_syllabus(
    config: CourseConfig,
    toc_data: dict,
    course_path: str | Path,
) -> None:
    """Write course/index.qmd. Overwrites any prior content (including the
    init placeholder) on every update run."""
    content = _build_syllabus(config, toc_data)
    (Path(course_path) / "index.qmd").write_text(content, encoding="utf-8")
