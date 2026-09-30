"""Generate course/index.qmd (the syllabus) -- step 8 of the update flow."""

from datetime import date
from pathlib import Path

from .hw import assignment_stems
from .schema import CourseConfig, Lecture, Part


def _short_date(d: date) -> str:
    """'Sep 28' -- abbreviated month, no leading zero on day."""
    return d.strftime("%b") + f" {d.day}"


def _label_link_targets(toc_data: dict) -> dict[str, str]:
    """Map each section label to a markdown link target 'path#label'.

    The path is the chapter's .qmd path (relative to the project root),
    which Quarto converts to .html in rendered output. When the chapter
    isn't included in the current profile the link is simply dead."""
    targets: dict[str, str] = {}
    for group in (toc_data.get("chapters", []), toc_data.get("appendices", [])):
        for chapter in group:
            path = chapter.get("path", "")
            if chapter.get("label"):
                targets[chapter["label"]] = f"{path}#{chapter['label']}"
            for sec in chapter.get("sections", []):
                if sec.get("label"):
                    targets[sec["label"]] = f"{path}#{sec['label']}"
    return targets


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


def _lecture_topic(
    lec: Lecture,
    titles: dict[str, str],
    chapter_labels: set[str],
    link_targets: dict[str, str] | None = None,
) -> str:
    first_label = lec.sections[0] if lec.sections else None
    if lec.name:
        text = lec.name
    elif first_label is None:
        return "—"
    elif first_label in chapter_labels:
        text = "Introduction"
    else:
        text = titles.get(first_label, first_label)
    if link_targets and first_label and first_label in link_targets:
        return f"[{text}]({link_targets[first_label]})"
    return text


def _schedule_parts(config: CourseConfig, toc_data: dict) -> list[str]:
    """Build the '## Schedule' section as a single table.

    If the course defines parts, bold part-name rows act as visual
    separators within the table. Otherwise a flat date/topic table
    is produced."""
    if not config.lectures:
        return []

    titles = _label_titles(toc_data)
    link_targets = _label_link_targets(toc_data)
    chapter_labels = {
        ch.get("label")
        for group in (toc_data.get("chapters", []), toc_data.get("appendices", []))
        for ch in group
        if ch.get("label")
    }

    def _topic(lec: Lecture) -> str:
        return _lecture_topic(lec, titles, chapter_labels, link_targets)

    rows: list[list[str]] = []

    if config.parts:
        in_part: set = {lec.date for p in config.parts for lec in p.lectures}
        for part in config.parts:
            rows.append([f"**{part.part}**", ""])
            for lec in part.lectures:
                rows.append([_short_date(lec.date), _topic(lec)])
        for lec in config.lectures:
            if lec.date not in in_part:
                rows.append([_short_date(lec.date), _topic(lec)])
    else:
        for lec in config.lectures:
            rows.append([_short_date(lec.date), _topic(lec)])

    return [
        "",
        "## Schedule",
        "",
        "::: {#coursecraft-schedule}",
        _md_table(["Date", "Topic"], rows),
        ":::",
    ]


def _build_syllabus(config: CourseConfig, toc_data: dict) -> str:
    sec = config.section
    instructor_cell = (
        f"[{sec.instructor}](mailto:{sec.instructor_email})"
        if sec.instructor_email
        else sec.instructor
    )
    info_rows = [
        ["**Course**", sec.course_number],
        ["**Term**", sec.term],
        ["**Instructor**", instructor_cell],
        ["**Location**", sec.location],
        ["**Meeting times**", sec.meeting_times],
    ]

    parts: list[str] = [
        "---",
        "number-sections: false",
        "---",
        "",
        "# Syllabus {.unnumbered}",
        "",
    ]

    if sec.description:
        parts += [sec.description, ""]

    parts.append(_md_table(["", ""], info_rows))

    parts += _schedule_parts(config, toc_data)

    if config.assignments:
        stems = assignment_stems(config)
        assignment_rows = [
            [f"[{a.name}](#){{data-hw-stem=\"{stem}\"}}", _short_date(a.assigned), _short_date(a.due)]
            for stem, a in zip(stems, config.assignments)
        ]
        parts += [
            "",
            "## Assignments",
            "",
            "::: {#coursecraft-assignments}",
            _md_table(["", "Assigned", "Due"], assignment_rows),
            ":::",
        ]

    parts += [
        "",
        "```{=html}",
        "<script>",
        "document.addEventListener('DOMContentLoaded', function () {",
        "  function deadLink(a) {",
        "    a.style.color = 'inherit';",
        "    a.style.textDecoration = 'none';",
        "    a.style.cursor = 'default';",
        "    a.style.opacity = '0.4';",
        "    a.addEventListener('click', function (e) { e.preventDefault(); });",
        "  }",
        "  var s = window.coursecraftSections;",
        "  if (s) {",
        "    document.querySelectorAll('#coursecraft-schedule a[href]').forEach(function (a) {",
        "      var label = a.href.split('#')[1];",
        "      if (label && s[label] === false) deadLink(a);",
        "    });",
        "  }",
        "  var hw = window.coursecraftHwFiles;",
        "  if (hw) {",
        "    document.querySelectorAll('#coursecraft-assignments a[data-hw-stem]').forEach(function (a) {",
        "      var stem = a.getAttribute('data-hw-stem');",
        "      var solFile = stem + '-solutions.html';",
        "      var baseFile = stem + '.html';",
        "      if (hw.indexOf(solFile) !== -1) {",
        "        a.href = solFile;",
        "      } else if (hw.indexOf(baseFile) !== -1) {",
        "        a.href = baseFile;",
        "      } else {",
        "        deadLink(a);",
        "      }",
        "    });",
        "  }",
        "});",
        "</script>",
        "```",
        "",
    ]
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
