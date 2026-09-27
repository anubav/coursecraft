import pytest

from coursecraft.hw import _hw_content, _solutions_content, generate_homework_files
from coursecraft.schema import Assignment, CourseConfig


def _assignment(**kwargs) -> Assignment:
    defaults = {
        "name": "Homework 1",
        "assigned": "2027-01-08",
        "due": "2027-01-15",
        "exercises": ["modus-ponens", "modus-tollens"],
        "show_solutions": False,
        "is_exam": False,
    }
    return Assignment.model_validate({**defaults, **kwargs})


def _config(assignments: list[dict]) -> CourseConfig:
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
        "assignments": assignments,
    })


class TestHwContent:
    def test_h1_heading_contains_name(self):
        content = _hw_content(_assignment(name="Homework 1"))
        assert "# Homework 1 {.unnumbered}" in content

    def test_no_frontmatter_title(self):
        content = _hw_content(_assignment(name="Homework 1"))
        assert "title:" not in content

    def test_due_date_present(self):
        content = _hw_content(_assignment(due="2027-11-02"))
        assert "**Due: November 2, 2027**" in content

    def test_macros_include_injected_when_provided(self):
        content = _hw_content(_assignment(), macros_include="/assets/macros/macros.qmd")
        assert "{{< include /assets/macros/macros.qmd >}}" in content

    def test_macros_include_absent_when_not_provided(self):
        content = _hw_content(_assignment())
        assert "macros" not in content

    def test_due_date_no_leading_zero_on_day(self):
        content = _hw_content(_assignment(due="2027-01-08"))
        assert "January 8, 2027" in content
        assert "January 08" not in content

    def test_each_exercise_has_cross_ref(self):
        content = _hw_content(_assignment(exercises=["modus-ponens", "modus-tollens"]))
        assert "@exr-modus-ponens" in content
        assert "@exr-modus-tollens" in content

    def test_each_exercise_has_include(self):
        content = _hw_content(_assignment(exercises=["modus-ponens"]))
        assert "{{< include /exercises/modus-ponens.qmd >}}" in content

    def test_cross_ref_appears_before_include(self):
        content = _hw_content(_assignment(exercises=["modus-ponens"]))
        ref_pos = content.index("@exr-modus-ponens")
        inc_pos = content.index("{{< include /exercises/modus-ponens.qmd >}}")
        assert ref_pos < inc_pos

    def test_no_solution_include_in_hw_file(self):
        content = _hw_content(_assignment(exercises=["modus-ponens"]))
        assert "/solutions/" not in content

    def test_empty_exercises_produces_valid_file(self):
        content = _hw_content(_assignment(exercises=[]))
        assert "{.unnumbered}" in content
        assert "@exr" not in content


class TestSolutionsContent:
    def test_title_has_with_solutions_suffix(self):
        content = _solutions_content(_assignment(name="Homework 1"))
        assert "# Homework 1 (with solutions) {.unnumbered}" in content

    def test_no_frontmatter_title(self):
        content = _solutions_content(_assignment(name="Homework 1"))
        assert "title:" not in content

    def test_macros_include_injected_when_provided(self):
        content = _solutions_content(_assignment(), macros_include="/assets/macros/macros.qmd")
        assert "{{< include /assets/macros/macros.qmd >}}" in content

    def test_no_due_date_in_solutions(self):
        content = _solutions_content(_assignment(due="2027-01-15"))
        assert "Due" not in content

    def test_exercise_include_present(self):
        content = _solutions_content(_assignment(exercises=["modus-ponens"]))
        assert "{{< include /exercises/modus-ponens.qmd >}}" in content

    def test_solution_include_present(self):
        content = _solutions_content(_assignment(exercises=["modus-ponens"]))
        assert "{{< include /solutions/modus-ponens.qmd >}}" in content

    def test_exercise_include_before_solution_include(self):
        content = _solutions_content(_assignment(exercises=["modus-ponens"]))
        ex_pos = content.index("{{< include /exercises/modus-ponens.qmd >}}")
        sol_pos = content.index("{{< include /solutions/modus-ponens.qmd >}}")
        assert ex_pos < sol_pos

    def test_cross_ref_appears_before_exercise_include(self):
        content = _solutions_content(_assignment(exercises=["modus-ponens"]))
        ref_pos = content.index("@exr-modus-ponens")
        inc_pos = content.index("{{< include /exercises/modus-ponens.qmd >}}")
        assert ref_pos < inc_pos

    def test_multiple_exercises_all_interleaved(self):
        content = _solutions_content(_assignment(exercises=["ex-a", "ex-b"]))
        pos_ex_a = content.index("{{< include /exercises/ex-a.qmd >}}")
        pos_sol_a = content.index("{{< include /solutions/ex-a.qmd >}}")
        pos_ex_b = content.index("{{< include /exercises/ex-b.qmd >}}")
        pos_sol_b = content.index("{{< include /solutions/ex-b.qmd >}}")
        assert pos_ex_a < pos_sol_a < pos_ex_b < pos_sol_b


class TestGenerateHomeworkFiles:
    def test_hw_file_created(self, tmp_path):
        cfg = _config([{
            "name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
            "exercises": ["modus-ponens"],
        }])
        generate_homework_files(cfg, tmp_path)
        assert (tmp_path / "hw-01.qmd").exists()

    def test_hw_file_content_is_correct(self, tmp_path):
        cfg = _config([{
            "name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
            "exercises": ["modus-ponens"],
        }])
        generate_homework_files(cfg, tmp_path)
        content = (tmp_path / "hw-01.qmd").read_text()
        assert "# Homework 1 {.unnumbered}" in content
        assert "January 15, 2027" in content
        assert "@exr-modus-ponens" in content
        assert "title:" not in content

    def test_macros_include_written_when_provided(self, tmp_path):
        cfg = _config([{
            "name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
            "exercises": [],
        }])
        generate_homework_files(cfg, tmp_path, macros_include="/assets/macros/macros.qmd")
        content = (tmp_path / "hw-01.qmd").read_text()
        assert "{{< include /assets/macros/macros.qmd >}}" in content

    def test_solutions_file_created_when_show_solutions_true(self, tmp_path):
        cfg = _config([{
            "name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
            "exercises": ["modus-ponens"], "show_solutions": True,
        }])
        generate_homework_files(cfg, tmp_path)
        assert (tmp_path / "hw-01-solutions.qmd").exists()

    def test_no_solutions_file_when_show_solutions_false(self, tmp_path):
        cfg = _config([{
            "name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
            "exercises": ["modus-ponens"], "show_solutions": False,
        }])
        generate_homework_files(cfg, tmp_path)
        assert not (tmp_path / "hw-01-solutions.qmd").exists()

    def test_exam_uses_exam_prefix(self, tmp_path):
        cfg = _config([{
            "name": "Midterm", "assigned": "2027-02-01", "due": "2027-02-01",
            "exercises": [], "is_exam": True,
        }])
        generate_homework_files(cfg, tmp_path)
        assert (tmp_path / "exam-01.qmd").exists()
        assert not (tmp_path / "hw-01.qmd").exists()

    def test_hw_and_exam_use_separate_counters(self, tmp_path):
        cfg = _config([
            {"name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
             "exercises": []},
            {"name": "Midterm", "assigned": "2027-02-01", "due": "2027-02-01",
             "exercises": [], "is_exam": True},
            {"name": "Homework 2", "assigned": "2027-02-08", "due": "2027-02-15",
             "exercises": []},
        ])
        generate_homework_files(cfg, tmp_path)
        assert (tmp_path / "hw-01.qmd").exists()
        assert (tmp_path / "exam-01.qmd").exists()
        assert (tmp_path / "hw-02.qmd").exists()

    def test_multiple_hw_numbered_sequentially(self, tmp_path):
        cfg = _config([
            {"name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
             "exercises": []},
            {"name": "Homework 2", "assigned": "2027-01-22", "due": "2027-01-29",
             "exercises": []},
        ])
        generate_homework_files(cfg, tmp_path)
        assert (tmp_path / "hw-01.qmd").exists()
        assert (tmp_path / "hw-02.qmd").exists()

    def test_stale_hw_files_removed_on_rerun(self, tmp_path):
        """If an assignment is removed between runs, its file must not persist."""
        cfg_two = _config([
            {"name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
             "exercises": []},
            {"name": "Homework 2", "assigned": "2027-01-22", "due": "2027-01-29",
             "exercises": []},
        ])
        generate_homework_files(cfg_two, tmp_path)
        assert (tmp_path / "hw-02.qmd").exists()

        cfg_one = _config([
            {"name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
             "exercises": []},
        ])
        generate_homework_files(cfg_one, tmp_path)
        assert (tmp_path / "hw-01.qmd").exists()
        assert not (tmp_path / "hw-02.qmd").exists()

    def test_stale_solutions_file_removed_when_solutions_disabled(self, tmp_path):
        cfg_with = _config([{
            "name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
            "exercises": [], "show_solutions": True,
        }])
        generate_homework_files(cfg_with, tmp_path)
        assert (tmp_path / "hw-01-solutions.qmd").exists()

        cfg_without = _config([{
            "name": "Homework 1", "assigned": "2027-01-08", "due": "2027-01-15",
            "exercises": [], "show_solutions": False,
        }])
        generate_homework_files(cfg_without, tmp_path)
        assert not (tmp_path / "hw-01-solutions.qmd").exists()
