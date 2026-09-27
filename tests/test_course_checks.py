"""Tests for the A/B/C/D cross-validation checks in course_checks.py."""

import copy

import pytest
import yaml

from coursecraft.course_checks import (
    check_labels_exist,
    check_exercises_exist,
    check_solutions_exist,
    check_label_ordering,
    run_course_checks,
)
from coursecraft.schema import CourseConfig


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_config_dict():
    return {
        "course": {
            "title": "Introduction to Logic",
            "notes_repo": "https://github.com/example/logic-notes.git",
        },
        "section": {
            "instructor": "Jane Smith",
            "course_number": "PHIL 201",
            "term": "Fall 2026",
            "location": "Room 1",
            "meeting_times": "MWF 10:30",
            "start_date": "2026-09-28",
            "end_date": "2026-12-11",
        },
        "lectures": [
            {"date": "2026-09-28", "notes_end": "sec-ch1-arguments"},
            {"date": "2026-09-30", "notes_end": "sec-ch1-validity"},
        ],
        "assignments": [
            {
                "name": "hw-01",
                "assigned": "2026-09-30",
                "due": "2026-10-07",
                "exercises": ["expressions"],
            },
        ],
    }


@pytest.fixture
def base_config(base_config_dict):
    return CourseConfig.model_validate(base_config_dict)


@pytest.fixture
def base_toc():
    """A minimal toc_data dict with labels matching the base_config lectures."""
    return {
        "chapters": [
            {
                "path": "chapters/ch1.qmd",
                "label": "sec-ch1",
                "title": "Chapter 1",
                "sections": [
                    {"label": "sec-ch1-arguments", "title": "Arguments"},
                    {"label": "sec-ch1-validity", "title": "Validity"},
                ],
            }
        ],
        "appendices": [],
    }


# ---------------------------------------------------------------------------
# Check A: labels exist
# ---------------------------------------------------------------------------

class TestCheckLabelsExist:
    def test_all_labels_present_returns_empty(self, base_config, base_toc):
        assert check_labels_exist(base_config, base_toc) == []

    def test_missing_notes_end_reported(self, base_config_dict, base_toc):
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["notes_end"] = "sec-ch1-nonexistent"
        config = CourseConfig.model_validate(data)
        problems = check_labels_exist(config, base_toc)
        assert len(problems) == 1
        assert "sec-ch1-nonexistent" in problems[0]
        assert "notes_end" in problems[0]

    def test_missing_notes_start_reported(self, base_config_dict, base_toc):
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["notes_start"] = "sec-ch1-ghost"
        config = CourseConfig.model_validate(data)
        problems = check_labels_exist(config, base_toc)
        assert len(problems) == 1
        assert "sec-ch1-ghost" in problems[0]
        assert "notes_start" in problems[0]

    def test_notes_start_none_not_checked(self, base_config, base_toc):
        # notes_start=None is the default for most lectures; must not appear
        assert check_labels_exist(base_config, base_toc) == []

    def test_all_lectures_checked_not_just_first(self, base_config_dict, base_toc):
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["notes_end"] = "sec-missing-a"
        data["lectures"][1]["notes_end"] = "sec-missing-b"
        config = CourseConfig.model_validate(data)
        problems = check_labels_exist(config, base_toc)
        assert len(problems) == 2

    def test_chapter_label_itself_counts(self, base_config_dict, base_toc):
        """A notes_end pointing at a chapter's own '#' heading label
        is valid -- chapter labels appear in toc_data too."""
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["notes_end"] = "sec-ch1"  # chapter label
        config = CourseConfig.model_validate(data)
        assert check_labels_exist(config, base_toc) == []

    def test_appendix_labels_counted(self, base_config_dict):
        toc = {
            "chapters": [],
            "appendices": [
                {
                    "path": "appendices/app-a.qmd",
                    "label": "sec-app-a",
                    "title": "Appendix A",
                    "sections": [
                        {"label": "sec-app-a-proofs", "title": "Proofs"},
                    ],
                }
            ],
        }
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["notes_end"] = "sec-app-a-proofs"
        data["lectures"][1]["notes_end"] = "sec-app-a-proofs"
        config = CourseConfig.model_validate(data)
        assert check_labels_exist(config, toc) == []

    def test_lecture_name_appears_in_problem(self, base_config_dict, base_toc):
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["name"] = "week-01"
        data["lectures"][0]["notes_end"] = "sec-missing"
        config = CourseConfig.model_validate(data)
        problems = check_labels_exist(config, base_toc)
        assert "week-01" in problems[0]


# ---------------------------------------------------------------------------
# Check B: exercises exist
# ---------------------------------------------------------------------------

class TestCheckExercisesExist:
    def test_present_exercise_no_problem(self, base_config, tmp_path):
        (tmp_path / "exercises").mkdir()
        (tmp_path / "exercises" / "expressions.qmd").write_text("")
        assert check_exercises_exist(base_config, tmp_path) == []

    def test_missing_exercise_reported(self, base_config, tmp_path):
        (tmp_path / "exercises").mkdir()
        problems = check_exercises_exist(base_config, tmp_path)
        assert len(problems) == 1
        assert "expressions" in problems[0]
        assert "hw-01" in problems[0]

    def test_all_exercises_checked_across_assignments(self, base_config_dict, tmp_path):
        data = copy.deepcopy(base_config_dict)
        data["assignments"].append({
            "name": "hw-02",
            "assigned": "2026-10-07",
            "due": "2026-10-14",
            "exercises": ["validity", "soundness"],
        })
        config = CourseConfig.model_validate(data)
        (tmp_path / "exercises").mkdir()
        (tmp_path / "exercises" / "expressions.qmd").write_text("")
        # validity and soundness both missing
        problems = check_exercises_exist(config, tmp_path)
        assert len(problems) == 2

    def test_no_assignments_no_problems(self, base_config_dict, tmp_path):
        data = copy.deepcopy(base_config_dict)
        data["assignments"] = []
        config = CourseConfig.model_validate(data)
        assert check_exercises_exist(config, tmp_path) == []

    def test_assignment_with_no_exercises_no_problems(self, base_config_dict, tmp_path):
        data = copy.deepcopy(base_config_dict)
        data["assignments"][0]["exercises"] = []
        config = CourseConfig.model_validate(data)
        assert check_exercises_exist(config, tmp_path) == []

    def test_exercises_dir_missing_still_reports(self, base_config, tmp_path):
        """If exercises/ doesn't exist at all, missing exercises should
        still be reported (not silently pass)."""
        problems = check_exercises_exist(base_config, tmp_path)
        assert len(problems) == 1


# ---------------------------------------------------------------------------
# Check C: solutions exist
# ---------------------------------------------------------------------------

class TestCheckSolutionsExist:
    def test_no_solutions_dir_skipped_entirely(self, base_config_dict, tmp_path):
        """solutions/ not existing is a valid state; the check is skipped."""
        data = copy.deepcopy(base_config_dict)
        data["assignments"][0]["show_solutions"] = True
        config = CourseConfig.model_validate(data)
        assert check_solutions_exist(config, tmp_path) == []

    def test_solutions_dir_exists_and_file_present(self, base_config_dict, tmp_path):
        data = copy.deepcopy(base_config_dict)
        data["assignments"][0]["show_solutions"] = True
        config = CourseConfig.model_validate(data)
        (tmp_path / "solutions").mkdir()
        (tmp_path / "solutions" / "expressions.qmd").write_text("")
        assert check_solutions_exist(config, tmp_path) == []

    def test_solutions_dir_exists_but_file_missing(self, base_config_dict, tmp_path):
        data = copy.deepcopy(base_config_dict)
        data["assignments"][0]["show_solutions"] = True
        config = CourseConfig.model_validate(data)
        (tmp_path / "solutions").mkdir()
        problems = check_solutions_exist(config, tmp_path)
        assert len(problems) == 1
        assert "expressions" in problems[0]
        assert "hw-01" in problems[0]

    def test_show_solutions_false_not_checked(self, base_config, tmp_path):
        """show_solutions=False (the default) -- no solution file required."""
        (tmp_path / "solutions").mkdir()
        assert check_solutions_exist(base_config, tmp_path) == []

    def test_only_show_solutions_assignments_checked(self, base_config_dict, tmp_path):
        data = copy.deepcopy(base_config_dict)
        data["assignments"][0]["show_solutions"] = False
        data["assignments"].append({
            "name": "hw-02",
            "assigned": "2026-10-07",
            "due": "2026-10-14",
            "exercises": ["validity"],
            "show_solutions": True,
        })
        config = CourseConfig.model_validate(data)
        (tmp_path / "solutions").mkdir()
        problems = check_solutions_exist(config, tmp_path)
        # Only hw-02's 'validity' is required; hw-01's 'expressions' is not
        assert len(problems) == 1
        assert "validity" in problems[0]
        assert "hw-02" in problems[0]


# ---------------------------------------------------------------------------
# Check D: label ordering
# ---------------------------------------------------------------------------

class TestCheckLabelOrdering:
    def test_forward_order_no_problems(self, base_config, base_toc):
        assert check_label_ordering(base_config, base_toc) == []

    def test_reversed_order_reported(self, base_config_dict, base_toc):
        """Swap notes_end so lecture 1 points at sec-ch1-validity (pos 1)
        and lecture 2 points at sec-ch1-arguments (pos 0) -- a reversal."""
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["notes_end"] = "sec-ch1-validity"
        data["lectures"][1]["notes_end"] = "sec-ch1-arguments"
        config = CourseConfig.model_validate(data)
        problems = check_label_ordering(config, base_toc)
        assert len(problems) == 1
        assert "sec-ch1-arguments" in problems[0]

    def test_equal_positions_allowed(self, base_config_dict, base_toc):
        """Two lectures pointing at the same notes_end is unusual but valid
        (a review lecture covering the same endpoint)."""
        data = copy.deepcopy(base_config_dict)
        data["lectures"][1]["notes_end"] = "sec-ch1-arguments"  # same as lecture 0
        config = CourseConfig.model_validate(data)
        assert check_label_ordering(config, base_toc) == []

    def test_unknown_label_skipped_not_cascaded(self, base_config_dict, base_toc):
        """A notes_end not in toc (caught by check A) must be skipped in D
        without resetting the frontier, so later lectures are still checked."""
        data = copy.deepcopy(base_config_dict)
        data["lectures"].append({
            "date": "2026-10-02",
            "notes_end": "sec-ch1-ghost",  # not in toc
        })
        data["lectures"].append({
            "date": "2026-10-05",
            "notes_end": "sec-ch1-arguments",  # earlier than validity
        })
        config = CourseConfig.model_validate(data)
        problems = check_label_ordering(config, base_toc)
        # lecture-04 (sec-ch1-arguments, pos 0) is before lecture-02's
        # frontier (sec-ch1-validity, pos 1). lecture-03 is skipped.
        assert len(problems) == 1
        assert "sec-ch1-arguments" in problems[0]

    def test_ordering_across_chapters(self):
        """Checks that position spans multiple chapters correctly."""
        toc = {
            "chapters": [
                {
                    "path": "ch1.qmd",
                    "label": "sec-ch1",
                    "title": "Ch1",
                    "sections": [
                        {"label": "sec-ch1-a", "title": "A"},
                        {"label": "sec-ch1-b", "title": "B"},
                    ],
                },
                {
                    "path": "ch2.qmd",
                    "label": "sec-ch2",
                    "title": "Ch2",
                    "sections": [
                        {"label": "sec-ch2-a", "title": "A"},
                    ],
                },
            ],
            "appendices": [],
        }
        config_dict = {
            "course": {
                "title": "Test",
                "notes_repo": "https://example.com/repo.git",
            },
            "section": {
                "instructor": "J",
                "course_number": "X 100",
                "term": "Fall 2026",
                "location": "Room 1",
                "meeting_times": "MWF",
                "start_date": "2026-09-01",
                "end_date": "2026-12-31",
            },
            "lectures": [
                {"date": "2026-09-01", "notes_end": "sec-ch1-b"},
                {"date": "2026-09-03", "notes_end": "sec-ch2-a"},
            ],
        }
        config = CourseConfig.model_validate(config_dict)
        assert check_label_ordering(config, toc) == []

    def test_going_back_across_chapters_reported(self):
        toc = {
            "chapters": [
                {
                    "path": "ch1.qmd", "label": "sec-ch1", "title": "Ch1",
                    "sections": [{"label": "sec-ch1-a", "title": "A"}],
                },
                {
                    "path": "ch2.qmd", "label": "sec-ch2", "title": "Ch2",
                    "sections": [{"label": "sec-ch2-a", "title": "A"}],
                },
            ],
            "appendices": [],
        }
        config_dict = {
            "course": {
                "title": "Test",
                "notes_repo": "https://example.com/repo.git",
            },
            "section": {
                "instructor": "J",
                "course_number": "X 100",
                "term": "Fall 2026",
                "location": "Room 1",
                "meeting_times": "MWF",
                "start_date": "2026-09-01",
                "end_date": "2026-12-31",
            },
            "lectures": [
                {"date": "2026-09-01", "notes_end": "sec-ch2-a"},
                {"date": "2026-09-03", "notes_end": "sec-ch1-a"},  # backwards
            ],
        }
        config = CourseConfig.model_validate(config_dict)
        problems = check_label_ordering(config, toc)
        assert len(problems) == 1
        assert "sec-ch1-a" in problems[0]

    def test_lecture_name_in_problem(self, base_config_dict, base_toc):
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["notes_end"] = "sec-ch1-validity"
        data["lectures"][1]["name"] = "review"
        data["lectures"][1]["notes_end"] = "sec-ch1-arguments"
        config = CourseConfig.model_validate(data)
        problems = check_label_ordering(config, base_toc)
        assert "review" in problems[0]

    def test_empty_lectures_no_problems(self, base_config_dict):
        data = copy.deepcopy(base_config_dict)
        data["lectures"] = []
        config = CourseConfig.model_validate(data)
        assert check_label_ordering(config, {"chapters": [], "appendices": []}) == []


# ---------------------------------------------------------------------------
# run_all_checks integration
# ---------------------------------------------------------------------------

class TestRunCourseChecks:
    def test_all_pass_returns_all_empty_lists(self, base_config, base_toc, tmp_path):
        (tmp_path / "exercises").mkdir()
        (tmp_path / "exercises" / "expressions.qmd").write_text("")
        results = run_course_checks(base_config, tmp_path, base_toc)
        assert set(results.keys()) == {
            "check_labels_exist",
            "check_exercises_exist",
            "check_solutions_exist",
            "check_label_ordering",
        }
        assert all(v == [] for v in results.values())

    def test_multiple_failures_all_reported(self, base_config_dict, base_toc, tmp_path):
        data = copy.deepcopy(base_config_dict)
        data["lectures"][0]["notes_end"] = "sec-ch1-ghost"  # A failure
        config = CourseConfig.model_validate(data)
        # exercises dir missing -> B failure too
        results = run_course_checks(config, tmp_path, base_toc)
        assert len(results["check_labels_exist"]) >= 1
        assert len(results["check_exercises_exist"]) >= 1
