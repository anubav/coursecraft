from datetime import date

import pytest
import yaml

from coursecraft.profiles import (
    ProfileMoment,
    build_timeline,
    generate_profiles,
    _visible_sections,
    _sections_metadata,
    _visible_chapters,
)
from coursecraft.schema import CourseConfig
from coursecraft.toc import label_positions


def _config(lectures=None, assignments=None) -> CourseConfig:
    return CourseConfig.model_validate({
        "course": {
            "title": "Test Course",
            "notes_repo": "https://example.com/notes.git",
        },
        "section": {
            "instructor": "Test Instructor",
            "course_number": "TEST 101",
            "term": "Winter 2027",
            "location": "Room 1",
            "meeting_times": "MWF 10:00",
            "start_date": "2027-01-01",
            "end_date": "2027-04-30",
        },
        "lectures": lectures or [],
        "assignments": assignments or [],
    })


def _base_toc() -> dict:
    """Minimal toc_data: two chapters, three labeled sections total."""
    return {
        "chapters": [
            {
                "path": "chapters/ch1.qmd",
                "label": "sec-ch1",
                "title": "Chapter 1",
                "sections": [
                    {"label": "sec-ch1-intro", "title": "Introduction"},
                    {"label": "sec-ch1-arguments", "title": "Arguments"},
                ],
            },
            {
                "path": "chapters/ch2.qmd",
                "label": "sec-ch2",
                "title": "Chapter 2",
                "sections": [
                    {"label": "sec-ch2-basics", "title": "Basics"},
                ],
            },
        ],
        "appendices": [],
    }


def _lec(d: str, end: str = "sec-ch1-intro", start: str = None, cumulative: bool = None) -> dict:
    lec = {"date": d, "notes_end": end}
    if start:
        lec["notes_start"] = start
    if cumulative is not None:
        lec["cumulative"] = cumulative
    return lec


def _hw(name: str, assigned: str, due: str, show_solutions=False, is_exam=False) -> dict:
    return {
        "name": name,
        "assigned": assigned,
        "due": due,
        "show_solutions": show_solutions,
        "is_exam": is_exam,
        "exercises": [],
    }


class TestBuildTimelineEventDates:
    def test_empty_config_returns_empty_timeline(self):
        assert build_timeline(_config()) == []

    def test_lecture_dates_become_moments(self):
        cfg = _config(lectures=[_lec("2027-01-06"), _lec("2027-01-08", "sec-ch1-args")])
        moments = build_timeline(cfg)
        assert [m.date for m in moments] == [date(2027, 1, 6), date(2027, 1, 8)]

    def test_assignment_assigned_date_triggers_moment(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-10", "2027-01-17")],
        )
        dates = [m.date for m in build_timeline(cfg)]
        assert date(2027, 1, 10) in dates

    def test_assignment_due_triggers_moment_when_show_solutions(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-10", "2027-01-17", show_solutions=True)],
        )
        dates = [m.date for m in build_timeline(cfg)]
        assert date(2027, 1, 17) in dates

    def test_assignment_due_does_not_trigger_moment_without_solutions(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-10", "2027-01-17", show_solutions=False)],
        )
        dates = [m.date for m in build_timeline(cfg)]
        assert date(2027, 1, 17) not in dates

    def test_same_date_events_collapse_to_one_moment(self):
        cfg = _config(
            lectures=[_lec("2027-01-08", "sec-ch1-args")],
            assignments=[_hw("HW1", "2027-01-08", "2027-01-15")],
        )
        moments = build_timeline(cfg)
        assert len([m for m in moments if m.date == date(2027, 1, 8)]) == 1

    def test_moments_sorted_ascending(self):
        cfg = _config(
            lectures=[_lec("2027-01-13", "sec-ch1-validity"), _lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-08", "2027-01-20")],
        )
        moments = build_timeline(cfg)
        assert moments == sorted(moments, key=lambda m: m.date)


class TestBuildTimelineLectures:
    def test_moment_includes_all_lectures_up_to_its_date(self):
        cfg = _config(lectures=[
            _lec("2027-01-06"),
            _lec("2027-01-08", "sec-ch1-args"),
            _lec("2027-01-13", "sec-ch1-validity"),
        ])
        moments = build_timeline(cfg)
        jan8 = next(m for m in moments if m.date == date(2027, 1, 8))
        assert len(jan8.lectures) == 2
        assert all(lec.date <= date(2027, 1, 8) for lec in jan8.lectures)

    def test_first_moment_has_only_first_lecture(self):
        cfg = _config(lectures=[_lec("2027-01-06"), _lec("2027-01-08", "sec-ch1-args")])
        moments = build_timeline(cfg)
        assert len(moments[0].lectures) == 1

    def test_lectures_in_date_order_within_moment(self):
        cfg = _config(lectures=[
            _lec("2027-01-08", "sec-ch1-args"),
            _lec("2027-01-06"),
        ])
        moments = build_timeline(cfg)
        last = moments[-1]
        assert last.lectures[0].date < last.lectures[1].date

    def test_assignment_only_moment_has_no_lectures_before_first_lecture(self):
        """Assigned date precedes first lecture: no lectures in that moment."""
        cfg = _config(
            lectures=[_lec("2027-01-10", "sec-ch1-args")],
            assignments=[_hw("HW1", "2027-01-06", "2027-01-20")],
        )
        moments = build_timeline(cfg)
        jan6 = next(m for m in moments if m.date == date(2027, 1, 6))
        assert jan6.lectures == []


class TestBuildTimelineHwFiles:
    def test_hw_not_in_files_before_assigned(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-08", "2027-01-15")],
        )
        moments = build_timeline(cfg)
        jan6 = next(m for m in moments if m.date == date(2027, 1, 6))
        assert jan6.hw_files == []

    def test_hw_file_appears_on_assigned_date(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-08", "2027-01-15")],
        )
        moments = build_timeline(cfg)
        jan8 = next(m for m in moments if m.date == date(2027, 1, 8))
        assert "hw-01.qmd" in jan8.hw_files

    def test_solutions_replace_hw_after_due_date(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-08", "2027-01-15", show_solutions=True)],
        )
        moments = build_timeline(cfg)
        jan15 = next(m for m in moments if m.date == date(2027, 1, 15))
        assert "hw-01-solutions.qmd" in jan15.hw_files
        assert "hw-01.qmd" not in jan15.hw_files

    def test_hw_stays_without_solutions_when_show_solutions_false(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-08", "2027-01-15", show_solutions=False)],
        )
        # due date doesn't trigger a moment, so check the assigned-date moment
        moments = build_timeline(cfg)
        jan8 = next(m for m in moments if m.date == date(2027, 1, 8))
        assert "hw-01.qmd" in jan8.hw_files
        assert "hw-01-solutions.qmd" not in jan8.hw_files

    def test_exam_uses_exam_prefix(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("Midterm", "2027-02-01", "2027-02-01", is_exam=True)],
        )
        moments = build_timeline(cfg)
        feb1 = next(m for m in moments if m.date == date(2027, 2, 1))
        assert "exam-01.qmd" in feb1.hw_files

    def test_separate_counters_for_hw_and_exam(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[
                _hw("HW1", "2027-01-08", "2027-01-15"),
                _hw("Midterm", "2027-02-01", "2027-02-01", is_exam=True),
                _hw("HW2", "2027-02-08", "2027-02-15"),
            ],
        )
        moments = build_timeline(cfg)
        last = moments[-1]
        assert "hw-01.qmd" in last.hw_files
        assert "exam-01.qmd" in last.hw_files
        assert "hw-02.qmd" in last.hw_files

    def test_hw_files_in_assignment_order(self):
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[
                _hw("HW1", "2027-01-08", "2027-01-15"),
                _hw("HW2", "2027-01-08", "2027-01-22"),
            ],
        )
        moments = build_timeline(cfg)
        jan8 = next(m for m in moments if m.date == date(2027, 1, 8))
        assert jan8.hw_files == ["hw-01.qmd", "hw-02.qmd"]

    def test_assigned_same_day_as_due_with_solutions(self):
        """An assignment assigned and due on the same date with show_solutions=True:
        only one moment, and it immediately shows solutions."""
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-15", "2027-01-15", show_solutions=True)],
        )
        moments = build_timeline(cfg)
        jan15 = next(m for m in moments if m.date == date(2027, 1, 15))
        assert "hw-01-solutions.qmd" in jan15.hw_files


class TestVisibleSections:
    def test_cumulative_lecture_reveals_up_to_end(self):
        toc = _base_toc()
        positions = label_positions(toc)
        cfg = _config(lectures=[_lec("2027-01-06", "sec-ch1-intro")])
        moment = build_timeline(cfg)[0]
        visible = _visible_sections(moment, positions)
        assert "sec-ch1" in visible
        assert "sec-ch1-intro" in visible
        assert "sec-ch1-arguments" not in visible
        assert "sec-ch2" not in visible

    def test_cumulative_lecture_at_end_reveals_all(self):
        toc = _base_toc()
        positions = label_positions(toc)
        cfg = _config(lectures=[_lec("2027-01-06", "sec-ch2-basics")])
        moment = build_timeline(cfg)[0]
        visible = _visible_sections(moment, positions)
        assert visible == {"sec-ch1", "sec-ch1-intro", "sec-ch1-arguments",
                           "sec-ch2", "sec-ch2-basics"}

    def test_windowed_lecture_reveals_only_its_range(self):
        toc = _base_toc()
        positions = label_positions(toc)
        cfg = _config(lectures=[
            _lec("2027-01-06", "sec-ch1-intro"),                           # cumulative: sec-ch1, sec-ch1-intro
            _lec("2027-01-08", end="sec-ch2-basics",
                 start="sec-ch2", cumulative=False),                       # windowed: sec-ch2, sec-ch2-basics
        ])
        moment = build_timeline(cfg)[1]  # Jan 8
        visible = _visible_sections(moment, positions)
        assert "sec-ch1" in visible
        assert "sec-ch1-intro" in visible
        assert "sec-ch1-arguments" not in visible   # gap left by windowed
        assert "sec-ch2" in visible
        assert "sec-ch2-basics" in visible

    def test_later_cumulative_fills_gaps_from_windowed(self):
        toc = _base_toc()
        positions = label_positions(toc)
        cfg = _config(lectures=[
            _lec("2027-01-06", "sec-ch1-intro"),
            _lec("2027-01-08", end="sec-ch2-basics",
                 start="sec-ch2", cumulative=False),
            _lec("2027-01-13", "sec-ch2-basics"),   # cumulative: fills sec-ch1-arguments gap
        ])
        moment = build_timeline(cfg)[2]  # Jan 13
        visible = _visible_sections(moment, positions)
        assert "sec-ch1-arguments" in visible        # gap now filled

    def test_unknown_label_skipped_gracefully(self):
        toc = _base_toc()
        positions = label_positions(toc)
        cfg = _config(lectures=[_lec("2027-01-06", "sec-does-not-exist")])
        moment = build_timeline(cfg)[0]
        visible = _visible_sections(moment, positions)
        assert visible == set()   # unknown end label → nothing revealed

    def test_no_lectures_in_moment_means_nothing_visible(self):
        toc = _base_toc()
        positions = label_positions(toc)
        cfg = _config(
            lectures=[_lec("2027-01-10", "sec-ch1-intro")],
            assignments=[_hw("HW1", "2027-01-06", "2027-01-20")],
        )
        moments = build_timeline(cfg)
        jan6 = next(m for m in moments if m.date == date(2027, 1, 6))
        visible = _visible_sections(jan6, positions)
        assert visible == set()


class TestSectionsMetadata:
    def test_all_labels_present_in_output(self):
        toc = _base_toc()
        visible = {"sec-ch1", "sec-ch1-intro"}
        result = _sections_metadata(visible, toc)
        assert set(result.keys()) == {
            "sec-ch1", "sec-ch1-intro", "sec-ch1-arguments",
            "sec-ch2", "sec-ch2-basics",
        }

    def test_visible_labels_are_true(self):
        toc = _base_toc()
        result = _sections_metadata({"sec-ch1", "sec-ch1-intro"}, toc)
        assert result["sec-ch1"] is True
        assert result["sec-ch1-intro"] is True

    def test_invisible_labels_are_false(self):
        toc = _base_toc()
        result = _sections_metadata({"sec-ch1", "sec-ch1-intro"}, toc)
        assert result["sec-ch1-arguments"] is False
        assert result["sec-ch2"] is False

    def test_output_in_document_order(self):
        toc = _base_toc()
        result = _sections_metadata(set(), toc)
        assert list(result.keys()) == [
            "sec-ch1", "sec-ch1-intro", "sec-ch1-arguments",
            "sec-ch2", "sec-ch2-basics",
        ]


class TestVisibleChapters:
    def test_chapter_with_visible_section_is_included(self):
        toc = _base_toc()
        chapters, appendices = _visible_chapters({"sec-ch1-intro"}, toc)
        assert "chapters/ch1.qmd" in chapters
        assert appendices == []

    def test_chapter_with_no_visible_labels_is_excluded(self):
        toc = _base_toc()
        chapters, _ = _visible_chapters({"sec-ch2-basics"}, toc)
        assert "chapters/ch1.qmd" not in chapters
        assert "chapters/ch2.qmd" in chapters

    def test_chapter_visible_by_chapter_label_alone(self):
        toc = _base_toc()
        chapters, _ = _visible_chapters({"sec-ch1"}, toc)
        assert "chapters/ch1.qmd" in chapters

    def test_empty_visible_set_excludes_all(self):
        toc = _base_toc()
        chapters, appendices = _visible_chapters(set(), toc)
        assert chapters == []
        assert appendices == []

    def test_all_visible_includes_all(self):
        toc = _base_toc()
        all_labels = {"sec-ch1", "sec-ch1-intro", "sec-ch1-arguments",
                      "sec-ch2", "sec-ch2-basics"}
        chapters, _ = _visible_chapters(all_labels, toc)
        assert chapters == ["chapters/ch1.qmd", "chapters/ch2.qmd"]

    def test_chapter_order_matches_toc_order(self):
        toc = _base_toc()
        chapters, _ = _visible_chapters(
            {"sec-ch1-intro", "sec-ch2-basics"}, toc
        )
        assert chapters == ["chapters/ch1.qmd", "chapters/ch2.qmd"]

    def test_appendices_filtered_separately(self):
        toc = {
            "chapters": [
                {"path": "chapters/ch1.qmd", "label": "sec-ch1",
                 "title": "Ch1", "sections": []},
            ],
            "appendices": [
                {"path": "appendices/app-a.qmd", "label": "sec-app-a",
                 "title": "App A", "sections": [
                     {"label": "sec-app-a-proofs", "title": "Proofs"},
                 ]},
            ],
        }
        chapters, appendices = _visible_chapters({"sec-app-a-proofs"}, toc)
        assert chapters == []
        assert appendices == ["appendices/app-a.qmd"]


class TestGenerateProfiles:
    def test_profile_file_written_per_moment(self, tmp_path):
        toc = _base_toc()
        cfg = _config(lectures=[_lec("2027-01-06"), _lec("2027-01-08", "sec-ch1-arguments")])
        generate_profiles(cfg, toc, tmp_path)
        assert (tmp_path / "_quarto-2027-01-06.yml").exists()
        assert (tmp_path / "_quarto-2027-01-08.yml").exists()

    def test_profile_contains_output_dir(self, tmp_path):
        toc = _base_toc()
        cfg = _config(lectures=[_lec("2027-01-06")])
        generate_profiles(cfg, toc, tmp_path)
        data = yaml.safe_load((tmp_path / "_quarto-2027-01-06.yml").read_text())
        assert data["project"]["output-dir"] == "_book/2027-01-06"

    def test_profile_sections_metadata_correct(self, tmp_path):
        toc = _base_toc()
        cfg = _config(lectures=[_lec("2027-01-06", "sec-ch1-intro")])
        generate_profiles(cfg, toc, tmp_path)
        data = yaml.safe_load((tmp_path / "_quarto-2027-01-06.yml").read_text())
        sections = data["metadata"]["sections"]
        assert sections["sec-ch1-intro"] is True
        assert sections["sec-ch1-arguments"] is False

    def test_profile_contains_visible_chapters(self, tmp_path):
        toc = _base_toc()
        cfg = _config(lectures=[_lec("2027-01-06", "sec-ch1-intro")])
        generate_profiles(cfg, toc, tmp_path)
        data = yaml.safe_load((tmp_path / "_quarto-2027-01-06.yml").read_text())
        assert "chapters/ch1.qmd" in data["book"]["chapters"]
        assert "chapters/ch2.qmd" not in data["book"]["chapters"]

    def test_chapter_not_in_profile_when_nothing_visible(self, tmp_path):
        toc = _base_toc()
        cfg = _config(lectures=[_lec("2027-01-06", "sec-ch2-basics")])
        generate_profiles(cfg, toc, tmp_path)
        data = yaml.safe_load((tmp_path / "_quarto-2027-01-06.yml").read_text())
        # Both chapters are visible when end is sec-ch2-basics (cumulative)
        assert "chapters/ch1.qmd" in data["book"]["chapters"]
        assert "chapters/ch2.qmd" in data["book"]["chapters"]

    def test_profile_hw_files_in_chapters(self, tmp_path):
        toc = _base_toc()
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-06", "2027-01-20")],
        )
        generate_profiles(cfg, toc, tmp_path)
        data = yaml.safe_load((tmp_path / "_quarto-2027-01-06.yml").read_text())
        assert "hw-01.qmd" in data["book"]["chapters"]
        assert "hw-01.qmd" not in data["book"].get("appendices", [])

    def test_no_hw_files_before_assigned(self, tmp_path):
        toc = _base_toc()
        cfg = _config(
            lectures=[_lec("2027-01-06")],
            assignments=[_hw("HW1", "2027-01-08", "2027-01-20")],
        )
        generate_profiles(cfg, toc, tmp_path)
        data = yaml.safe_load((tmp_path / "_quarto-2027-01-06.yml").read_text())
        assert "hw-01.qmd" not in data["book"]["chapters"]

    def test_stale_profiles_removed_on_rerun(self, tmp_path):
        toc = _base_toc()
        cfg_two = _config(lectures=[_lec("2027-01-06"), _lec("2027-01-08", "sec-ch1-arguments")])
        generate_profiles(cfg_two, toc, tmp_path)
        assert (tmp_path / "_quarto-2027-01-08.yml").exists()

        cfg_one = _config(lectures=[_lec("2027-01-06")])
        generate_profiles(cfg_one, toc, tmp_path)
        assert (tmp_path / "_quarto-2027-01-06.yml").exists()
        assert not (tmp_path / "_quarto-2027-01-08.yml").exists()

    def test_empty_timeline_writes_no_files(self, tmp_path):
        toc = _base_toc()
        cfg = _config()
        generate_profiles(cfg, toc, tmp_path)
        assert list(tmp_path.glob("_quarto-*.yml")) == []
