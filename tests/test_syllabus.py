from datetime import date
from pathlib import Path

import pytest

from coursecraft.syllabus import generate_syllabus, _build_syllabus
from coursecraft.schema import CourseConfig


def _config(**overrides) -> CourseConfig:
    base = {
        "course": {
            "title": "Introduction to Logic",
            "notes_repo": "https://example.com/notes.git",
        },
        "section": {
            "instructor": "Jane Smith",
            "course_number": "PHIL 101",
            "term": "Fall 2026",
            "location": "Stuart 102",
            "meeting_times": "MWF 10:30",
            "start_date": "2026-09-28",
            "end_date": "2026-12-11",
        },
        "lectures": [],
        "assignments": [],
    }
    base.update(overrides)
    return CourseConfig.model_validate(base)


def _toc() -> dict:
    return {
        "chapters": [
            {
                "path": "chapters/ch1.qmd",
                "label": "sec-ch1",
                "title": "Argument Validity",
                "sections": [
                    {"label": "sec-ch1-intro", "title": "Introduction"},
                    {"label": "sec-ch1-proof", "title": "Proof"},
                ],
            },
            {
                "path": "chapters/ch2.qmd",
                "label": "sec-ch2",
                "title": "Propositional Logic",
                "sections": [
                    {"label": "sec-ch2-syntax", "title": "Syntax"},
                    {"label": "sec-ch2-semantics", "title": "Semantics"},
                ],
            },
        ],
        "appendices": [],
    }


# toc label positions:
# 0: sec-ch1         (chapter label)
# 1: sec-ch1-intro
# 2: sec-ch1-proof
# 3: sec-ch2
# 4: sec-ch2-syntax
# 5: sec-ch2-semantics


class TestBuildSyllabusHeader:
    def test_h1_heading_unnumbered(self):
        content = _build_syllabus(_config(), _toc())
        assert "# Syllabus {.unnumbered}" in content

    def test_course_number_and_title_in_info_table(self):
        content = _build_syllabus(_config(), _toc())
        assert "PHIL 101: Introduction to Logic" in content

    def test_term_in_info_table(self):
        content = _build_syllabus(_config(), _toc())
        assert "Fall 2026" in content

    def test_instructor_in_info_table(self):
        content = _build_syllabus(_config(), _toc())
        assert "Jane Smith" in content

    def test_location_in_info_table(self):
        content = _build_syllabus(_config(), _toc())
        assert "Stuart 102" in content

    def test_meeting_times_in_info_table(self):
        content = _build_syllabus(_config(), _toc())
        assert "MWF 10:30" in content

    def test_description_included_when_set(self):
        cfg = _config()
        cfg.section.description = "A great course."
        content = _build_syllabus(cfg, _toc())
        assert "A great course." in content

    def test_no_description_when_empty(self):
        content = _build_syllabus(_config(), _toc())
        assert "A great course." not in content


class TestScheduleTopics:
    def test_schedule_section_present_when_lectures_exist(self):
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro"]},
        ])
        assert "## Schedule" in _build_syllabus(cfg, _toc())

    def test_schedule_absent_when_no_lectures(self):
        assert "## Schedule" not in _build_syllabus(_config(), _toc())

    def test_first_section_label_determines_topic(self):
        """Topic is the title of the first label in sections."""
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro"]},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "Introduction" in content
        assert "### Argument Validity" in content

    def test_chapter_label_as_first_section_shows_introduction(self):
        """When sections[0] is a chapter label → topic = 'Introduction'."""
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1"]},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "Introduction" in content
        assert "### Argument Validity" in content

    def test_each_lecture_uses_own_first_section_as_topic(self):
        """Each lecture's topic is derived from its own sections[0]."""
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro"]},
            {"date": "2026-09-30", "sections": ["sec-ch1-proof"]},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "Proof" in content

    def test_windowed_lecture_uses_first_section_as_topic(self):
        """Windowed lectures also use sections[0] as the topic."""
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro", "sec-ch1-proof"],
             "cumulative": False},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "Introduction" in content

    def test_date_formatted_short_no_leading_zero(self):
        cfg = _config(lectures=[
            {"date": "2026-10-08", "sections": ["sec-ch1-intro"]},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "Oct 8" in content
        assert "Oct 08" not in content

    def test_explicit_name_overrides_derived_topic(self):
        """lec.name takes precedence over the label-derived topic."""
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro"], "name": "Overview"},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "Overview" in content
        assert "| Sep 28 | Introduction |" not in content
        assert "| Sep 28 | Overview |" in content

    def test_explicit_name_preserves_chapter_grouping(self):
        """Chapter heading is still derived from sections[0] even when name is set."""
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro"], "name": "Overview"},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "### Argument Validity" in content

    def test_empty_sections_falls_back_to_dash(self):
        """Lecture with no sections shows '—' as topic."""
        cfg = _config(lectures=[
            {"date": "2026-09-28"},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "—" in content


class TestScheduleChapterGrouping:
    def test_chapter_heading_emitted_when_chapter_changes(self):
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-proof"]},
            {"date": "2026-09-30", "sections": ["sec-ch2-syntax"]},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "### Argument Validity" in content
        assert "### Propositional Logic" in content

    def test_chapter_heading_not_repeated_for_same_chapter(self):
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro"]},
            {"date": "2026-09-30", "sections": ["sec-ch1-proof"]},
        ])
        content = _build_syllabus(cfg, _toc())
        assert content.count("### Argument Validity") == 1

    def test_chapter_heading_before_its_lectures(self):
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-proof"]},
            {"date": "2026-09-30", "sections": ["sec-ch2-syntax"]},
        ])
        content = _build_syllabus(cfg, _toc())
        ch1_pos = content.index("### Argument Validity")
        ch2_pos = content.index("### Propositional Logic")
        sep28_pos = content.index("Sep 28")
        sep30_pos = content.index("Sep 30")
        assert ch1_pos < sep28_pos < ch2_pos < sep30_pos


class TestBuildSyllabusAssignments:
    def test_assignments_section_present_when_assignments_exist(self):
        cfg = _config(
            lectures=[{"date": "2026-09-28", "sections": ["sec-ch1-intro"]}],
            assignments=[{
                "name": "Homework 1", "assigned": "2026-09-30",
                "due": "2026-10-07", "exercises": [],
            }],
        )
        assert "## Assignments" in _build_syllabus(cfg, _toc())

    def test_assignments_absent_when_none(self):
        assert "## Assignments" not in _build_syllabus(_config(), _toc())

    def test_assignment_name_in_table(self):
        cfg = _config(
            lectures=[{"date": "2026-09-28", "sections": ["sec-ch1-intro"]}],
            assignments=[{
                "name": "Homework 1", "assigned": "2026-09-30",
                "due": "2026-10-07", "exercises": [],
            }],
        )
        assert "Homework 1" in _build_syllabus(cfg, _toc())

    def test_assigned_and_due_dates_formatted(self):
        cfg = _config(
            lectures=[{"date": "2026-09-28", "sections": ["sec-ch1-intro"]}],
            assignments=[{
                "name": "Homework 1", "assigned": "2026-09-30",
                "due": "2026-10-07", "exercises": [],
            }],
        )
        content = _build_syllabus(cfg, _toc())
        assert "Sep 30" in content
        assert "Oct 7" in content


class TestGenerateSyllabus:
    def test_writes_index_qmd(self, tmp_path):
        generate_syllabus(_config(), _toc(), tmp_path)
        assert (tmp_path / "index.qmd").exists()

    def test_overwrites_existing_index_qmd(self, tmp_path):
        (tmp_path / "index.qmd").write_text("old content")
        generate_syllabus(_config(), _toc(), tmp_path)
        assert "old content" not in (tmp_path / "index.qmd").read_text()

    def test_full_output_has_expected_sections(self, tmp_path):
        cfg = _config(
            lectures=[{"date": "2026-09-28", "sections": ["sec-ch1-intro"]}],
            assignments=[{
                "name": "Homework 1", "assigned": "2026-09-30",
                "due": "2026-10-07", "exercises": [],
            }],
        )
        generate_syllabus(cfg, _toc(), tmp_path)
        content = (tmp_path / "index.qmd").read_text()
        assert "# Syllabus {.unnumbered}" in content
        assert "## Schedule" in content
        assert "## Assignments" in content
