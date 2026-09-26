import copy

import pytest
from pydantic import ValidationError

from coursecraft.schema import CourseConfig


@pytest.fixture
def base_config() -> dict:
    """A minimal, valid config dict. Tests mutate a deep copy of this
    rather than sharing state."""
    return {
        "course": {
            "title": "Introduction to Logic",
            "notes_repo": "https://github.com/example/logic-notes.git",
        },
        "section": {
            "instructor": "Jane Smith",
            "course_number": "PHIL 20100",
            "term": "Fall 2026",
            "location": "Cobb 201",
            "meeting_times": "MWF 10:30-11:20",
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


class TestValidConfig:
    def test_base_config_loads(self, base_config):
        config = CourseConfig.model_validate(base_config)
        assert config.course.title == "Introduction to Logic"
        assert len(config.lectures) == 2
        assert len(config.assignments) == 1

    def test_notes_branch_defaults_to_none(self, base_config):
        config = CourseConfig.model_validate(base_config)
        assert config.course.notes_branch is None

    def test_notes_branch_can_be_set(self, base_config):
        data = copy.deepcopy(base_config)
        data["course"]["notes_branch"] = "kevin-custom"
        config = CourseConfig.model_validate(data)
        assert config.course.notes_branch == "kevin-custom"

    def test_lectures_sorted_by_date(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"] = list(reversed(data["lectures"]))
        config = CourseConfig.model_validate(data)
        assert config.lectures[0].date < config.lectures[1].date


class TestEffectiveCumulative:
    def test_blank_notes_start_defaults_cumulative(self, base_config):
        config = CourseConfig.model_validate(base_config)
        assert config.lectures[0].effective_cumulative is True

    def test_explicit_notes_start_defaults_windowed(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"][1]["notes_start"] = "sec-ch1-arguments"
        config = CourseConfig.model_validate(data)
        lec = [l for l in config.lectures if l.notes_start][0]
        assert lec.effective_cumulative is False

    def test_explicit_cumulative_true_overrides_windowed_default(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"][1]["notes_start"] = "sec-ch1-arguments"
        data["lectures"][1]["cumulative"] = True
        config = CourseConfig.model_validate(data)
        lec = [l for l in config.lectures if l.notes_start][0]
        assert lec.effective_cumulative is True

    def test_explicit_cumulative_false_overrides_cumulative_default(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"][0]["cumulative"] = False
        config = CourseConfig.model_validate(data)
        assert config.lectures[0].effective_cumulative is False


class TestLectureName:
    def test_auto_numbered_when_unnamed(self, base_config):
        config = CourseConfig.model_validate(base_config)
        assert config.lecture_name(0) == "lecture-01"
        assert config.lecture_name(1) == "lecture-02"

    def test_explicit_name_used_when_given(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"][1]["name"] = "midterm-review"
        config = CourseConfig.model_validate(data)
        assert config.lecture_name(1) == "midterm-review"


class TestValidators:
    def test_duplicate_lecture_dates_rejected(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"][1]["date"] = data["lectures"][0]["date"]
        with pytest.raises(ValidationError, match="cannot share the same date"):
            CourseConfig.model_validate(data)

    def test_due_before_assigned_rejected(self, base_config):
        data = copy.deepcopy(base_config)
        data["assignments"][0]["due"] = "2026-09-01"
        with pytest.raises(ValidationError, match="is before assigned"):
            CourseConfig.model_validate(data)

    def test_bad_label_format_rejected(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"][0]["notes_end"] = "Arguments"
        with pytest.raises(ValidationError, match="should be a section label"):
            CourseConfig.model_validate(data)

    def test_bad_notes_start_label_also_rejected(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"][0]["notes_start"] = "Arguments"
        with pytest.raises(ValidationError, match="should be a section label"):
            CourseConfig.model_validate(data)

    def test_date_outside_term_rejected(self, base_config):
        data = copy.deepcopy(base_config)
        data["lectures"][0]["date"] = "2025-09-28"
        with pytest.raises(ValidationError, match="falls outside"):
            CourseConfig.model_validate(data)

    def test_end_date_before_start_date_rejected(self, base_config):
        data = copy.deepcopy(base_config)
        data["section"]["end_date"] = "2026-01-01"
        with pytest.raises(ValidationError, match="must be after"):
            CourseConfig.model_validate(data)

    def test_duplicate_assignment_names_rejected(self, base_config):
        data = copy.deepcopy(base_config)
        data["assignments"].append(copy.deepcopy(data["assignments"][0]))
        with pytest.raises(ValidationError, match="must be unique"):
            CourseConfig.model_validate(data)

    def test_exercise_as_path_rejected(self, base_config):
        data = copy.deepcopy(base_config)
        data["assignments"][0]["exercises"] = ["exercises/expressions.qmd"]
        with pytest.raises(ValidationError, match="bare name"):
            CourseConfig.model_validate(data)

    def test_exercise_bare_name_accepted(self, base_config):
        config = CourseConfig.model_validate(base_config)
        assert config.assignments[0].exercises == ["expressions"]


class TestLoadCourseInfo:
    """load_course_info is what fetch-notes uses -- must succeed even
    when section/lectures/assignments are still full of REPLACE_ME
    placeholders (e.g. right after `init`, before the course.yaml-
    filling wizard has run), since it only validates the course: block."""

    def test_ignores_placeholder_section(self, tmp_path):
        import yaml
        data = {
            "course": {
                "title": "REPLACE_ME",
                "notes_repo": "https://example.com/notes.git",
            },
            "section": {
                "instructor": "REPLACE_ME", "course_number": "REPLACE_ME",
                "term": "REPLACE_ME", "location": "REPLACE_ME",
                "meeting_times": "REPLACE_ME",
                "start_date": "REPLACE_ME", "end_date": "REPLACE_ME",
            },
            "lectures": [], "assignments": [],
        }
        path = tmp_path / "course.yaml"
        path.write_text(yaml.dump(data))

        info = CourseConfig.load_course_info(path)
        assert info.notes_repo == "https://example.com/notes.git"

    def test_notes_branch_available_too(self, tmp_path):
        import yaml
        data = {
            "course": {
                "title": "REPLACE_ME",
                "notes_repo": "https://example.com/notes.git",
                "notes_branch": "kevin-custom",
            },
        }
        path = tmp_path / "course.yaml"
        path.write_text(yaml.dump(data))

        info = CourseConfig.load_course_info(path)
        assert info.notes_branch == "kevin-custom"

    def test_missing_notes_repo_still_rejected(self, tmp_path):
        import yaml
        path = tmp_path / "course.yaml"
        path.write_text(yaml.dump({"course": {"title": "x"}}))

        with pytest.raises(ValidationError, match="Field required"):
            CourseConfig.load_course_info(path)

    def test_missing_course_block_rejected(self, tmp_path):
        import yaml
        path = tmp_path / "course.yaml"
        path.write_text(yaml.dump({"section": {}}))

        with pytest.raises(ValidationError):
            CourseConfig.load_course_info(path)


class TestAssignmentDefaults:
    def test_show_solutions_defaults_false(self, base_config):
        config = CourseConfig.model_validate(base_config)
        assert config.assignments[0].show_solutions is False

    def test_is_exam_defaults_false(self, base_config):
        config = CourseConfig.model_validate(base_config)
        assert config.assignments[0].is_exam is False
