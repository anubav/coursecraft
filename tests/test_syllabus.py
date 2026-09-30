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
    def test_syllabus_heading_unnumbered(self):
        content = _build_syllabus(_config(), _toc())
        assert "# Syllabus {.unnumbered}" in content

    def test_course_title_not_in_syllabus_body(self):
        # title goes into _quarto.yml via _strip_quarto_chapter_lists, not index.qmd
        content = _build_syllabus(_config(), _toc())
        assert "# Introduction to Logic" not in content

    def test_course_number_in_info_table(self):
        content = _build_syllabus(_config(), _toc())
        assert "PHIL 101" in content

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

    def test_description_before_info_table(self):
        cfg = _config()
        cfg.section.description = "A great course."
        content = _build_syllabus(cfg, _toc())
        assert content.index("A great course.") < content.index("**Course**")

    def test_no_description_when_empty(self):
        content = _build_syllabus(_config(), _toc())
        assert "A great course." not in content

    def test_instructor_email_links_name(self):
        cfg = _config()
        cfg.section.instructor_email = "jane@example.com"
        content = _build_syllabus(cfg, _toc())
        assert "[Jane Smith](mailto:jane@example.com)" in content

    def test_instructor_plain_when_no_email(self):
        content = _build_syllabus(_config(), _toc())
        assert "mailto:" not in content


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

    def test_chapter_label_as_first_section_shows_introduction(self):
        """When sections[0] is a chapter label → topic = 'Introduction'."""
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1"]},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "Introduction" in content

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
        assert "Introduction |" not in content

    def test_explicit_name_single_table_row(self):
        """Named lecture appears as a single row in the table, linked via sections[0]."""
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro"], "name": "Overview"},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "Sep 28" in content
        assert "[Overview](" in content

    def test_empty_sections_falls_back_to_dash(self):
        """Lecture with no sections shows '—' as topic."""
        cfg = _config(lectures=[
            {"date": "2026-09-28"},
        ])
        content = _build_syllabus(cfg, _toc())
        assert "—" in content


class TestScheduleParts:
    def _parts_config(self):
        return _config(lectures=[
            {"part": "Part I", "lectures": [
                {"date": "2026-09-28", "sections": ["sec-ch1-intro"]},
                {"date": "2026-09-30", "sections": ["sec-ch1-proof"]},
            ]},
            {"part": "Part II", "lectures": [
                {"date": "2026-10-05", "sections": ["sec-ch2-syntax"]},
            ]},
        ])

    def test_single_table_with_parts(self):
        content = _build_syllabus(self._parts_config(), _toc())
        assert content.count("| Date | Topic |") == 1

    def test_part_names_appear_as_bold_rows(self):
        content = _build_syllabus(self._parts_config(), _toc())
        assert "**Part I**" in content
        assert "**Part II**" in content

    def test_part_headers_before_their_lectures(self):
        content = _build_syllabus(self._parts_config(), _toc())
        p1_pos = content.index("**Part I**")
        p2_pos = content.index("**Part II**")
        sep28_pos = content.index("Sep 28")
        oct5_pos = content.index("Oct 5")
        assert p1_pos < sep28_pos < p2_pos < oct5_pos

    def test_no_parts_produces_single_flat_table(self):
        cfg = _config(lectures=[
            {"date": "2026-09-28", "sections": ["sec-ch1-intro"]},
            {"date": "2026-09-30", "sections": ["sec-ch1-proof"]},
        ])
        content = _build_syllabus(cfg, _toc())
        assert content.count("| Date | Topic |") == 1
        assert "**" not in content.split("## Schedule")[1].split("## Assignments")[0]


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
        assert "## Schedule" in content
        assert "## Assignments" in content
