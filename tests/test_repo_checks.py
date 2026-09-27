import copy

import pytest

from coursecraft.manifest import NotesManifest
from coursecraft.repo_checks import (
    check_globs_against_repo,
    check_missing_labels,
    check_duplicate_labels,
    check_dangling_includes,
    check_chapter_headings,
    check_exercise_labels,
    run_all_checks,
)


@pytest.fixture
def base_manifest() -> dict:
    return {
        "coursecraft_spec": "1.0",
        "conventions": {
            "chapter_glob": "chapters/*.qmd",
            "appendix_dir_glob": "appendices/*.qmd",
            "exercise_glob": "exercises/*.qmd",
            "insert_glob": "inserts/**/*.qmd",
        },
    }


def _make_minimal_repo(root, chapter_text=None, appendix_text=None):
    """A minimal, otherwise-valid repo: one chapter, one appendix, one
    exercise, one insert. Tests override chapter_text/appendix_text to
    inject a specific problem while leaving everything else correct,
    so each test isolates exactly one thing going wrong."""
    (root / "chapters").mkdir()
    (root / "chapters" / "one.qmd").write_text(
        chapter_text or "# Chapter One {#sec-one .chapter}\n\n## Intro {#sec-one-intro}\n"
    )
    (root / "appendices").mkdir()
    (root / "appendices" / "a.qmd").write_text(
        appendix_text or "# Appendix A {#sec-a .appendix}\n"
    )
    (root / "exercises").mkdir()
    (root / "exercises" / "e.qmd").write_text("An exercise.\n")
    (root / "inserts" / "sub").mkdir(parents=True)
    (root / "inserts" / "sub" / "i.qmd").write_text("An insert.\n")


class TestGlobsAgainstRepo:
    def test_matching_globs_report_no_problems(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_globs_against_repo(manifest, tmp_path) == []

    def test_glob_matching_nothing_reported(self, base_manifest, tmp_path):
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_globs_against_repo(manifest, tmp_path)
        assert len(problems) == 4
        assert any("chapter_glob" in p for p in problems)

    def test_missing_macros_include_reported(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        data = copy.deepcopy(base_manifest)
        data["conventions"]["macros_include"] = "/assets/macros/macros.qmd"
        manifest = NotesManifest.model_validate(data)
        problems = check_globs_against_repo(manifest, tmp_path)
        assert len(problems) == 1
        assert "macros_include" in problems[0]

    def test_existing_macros_include_not_reported(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        (tmp_path / "assets" / "macros").mkdir(parents=True)
        (tmp_path / "assets" / "macros" / "macros.qmd").touch()
        data = copy.deepcopy(base_manifest)
        data["conventions"]["macros_include"] = "/assets/macros/macros.qmd"
        manifest = NotesManifest.model_validate(data)
        assert check_globs_against_repo(manifest, tmp_path) == []


class TestMissingLabels:
    def test_clean_chapter_reports_nothing(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_missing_labels(manifest, tmp_path) == []

    def test_unlabeled_subsection_reported(self, base_manifest, tmp_path):
        _make_minimal_repo(
            tmp_path,
            chapter_text="# Chapter One {#sec-one .chapter}\n\n## Missing Label\n",
        )
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_missing_labels(manifest, tmp_path)
        assert len(problems) == 1
        assert "Missing Label" in problems[0]
        assert "one.qmd" in problems[0]

    def test_exercises_and_inserts_not_checked_for_sec_labels(self, base_manifest, tmp_path):
        """Exercise/insert fragments aren't sections and have no
        sec- label requirement -- an unlabeled ## inside one (unusual,
        but not this check's concern) must not be flagged."""
        _make_minimal_repo(tmp_path)
        (tmp_path / "exercises" / "e.qmd").write_text("## Some heading\n\ntext\n")
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_missing_labels(manifest, tmp_path) == []


class TestDuplicateLabels:
    def test_unique_labels_report_nothing(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_duplicate_labels(manifest, tmp_path) == []

    def test_duplicate_label_within_one_file_reported(self, base_manifest, tmp_path):
        chapter_text = (
            "# Chapter One {#sec-one .chapter}\n\n"
            ":::{#prp-foo .proposition}\nFirst claim.\n:::\n\n"
            ":::{#prp-foo .proposition}\nA different, second claim.\n:::\n"
        )
        _make_minimal_repo(tmp_path, chapter_text=chapter_text)
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_duplicate_labels(manifest, tmp_path)
        assert len(problems) == 1
        assert "prp-foo" in problems[0]

    def test_duplicate_label_across_two_files_reported(self, base_manifest, tmp_path):
        _make_minimal_repo(
            tmp_path,
            chapter_text="# Chapter One {#sec-one .chapter}\n\n:::{#def-x}\nfoo\n:::\n",
            appendix_text="# Appendix A {#sec-one .appendix}\n",  # reuses 'sec-one'
        )
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_duplicate_labels(manifest, tmp_path)
        assert any("sec-one" in p for p in problems)


class TestDanglingIncludes:
    def test_no_includes_reports_nothing(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_dangling_includes(manifest, tmp_path) == []

    def test_resolving_include_reports_nothing(self, base_manifest, tmp_path):
        chapter_text = (
            "# Chapter One {#sec-one .chapter}\n\n"
            "{{< include /exercises/e.qmd >}}\n"
        )
        _make_minimal_repo(tmp_path, chapter_text=chapter_text)
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_dangling_includes(manifest, tmp_path) == []

    def test_dangling_include_reported(self, base_manifest, tmp_path):
        chapter_text = (
            "# Chapter One {#sec-one .chapter}\n\n"
            "{{< include /exercises/does-not-exist.qmd >}}\n"
        )
        _make_minimal_repo(tmp_path, chapter_text=chapter_text)
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_dangling_includes(manifest, tmp_path)
        assert len(problems) == 1
        assert "does-not-exist.qmd" in problems[0]

    def test_relative_include_not_this_checks_concern(self, base_manifest, tmp_path):
        """A relative include resolves differently (against the
        including file's own directory) -- not this check's job."""
        chapter_text = (
            "# Chapter One {#sec-one .chapter}\n\n"
            "{{< include some-local-file.qmd >}}\n"
        )
        _make_minimal_repo(tmp_path, chapter_text=chapter_text)
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_dangling_includes(manifest, tmp_path) == []


class TestChapterHeadings:
    def test_well_formed_chapter_reports_nothing(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_chapter_headings(manifest, tmp_path) == []

    def test_missing_chapter_marker_class_reported(self, base_manifest, tmp_path):
        _make_minimal_repo(
            tmp_path,
            chapter_text="# Chapter One {#sec-one}\n\n## Intro {#sec-one-intro}\n",
        )
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_chapter_headings(manifest, tmp_path)
        assert len(problems) == 1
        assert ".chapter" in problems[0]

    def test_missing_chapter_label_reported(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path, chapter_text="# Chapter One\n")
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_chapter_headings(manifest, tmp_path)
        assert len(problems) == 1
        assert "no {#sec-...} label" in problems[0]

    def test_two_top_level_headings_reported(self, base_manifest, tmp_path):
        chapter_text = (
            "# Chapter One {#sec-one .chapter}\n\ntext\n\n"
            "# Stray Second Heading {#sec-stray}\n"
        )
        _make_minimal_repo(tmp_path, chapter_text=chapter_text)
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_chapter_headings(manifest, tmp_path)
        assert len(problems) == 1
        assert "2 top-level" in problems[0]

    def test_appendix_missing_label_reported_without_class_requirement(
        self, base_manifest, tmp_path
    ):
        """Appendices get the label check but not the chapter_marker_class
        check -- the manifest has no separate field for an appendix's
        own marker class, so this check must not invent that requirement."""
        _make_minimal_repo(tmp_path, appendix_text="# Appendix A\n")
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_chapter_headings(manifest, tmp_path)
        assert len(problems) == 1
        assert "no {#sec-...} label" in problems[0]
        assert "a.qmd" in problems[0]


class TestCheckExerciseLabels:
    def test_properly_labeled_exercise_reports_nothing(self, base_manifest, tmp_path):
        _make_minimal_repo(
            tmp_path,
            chapter_text=(
                "# Chapter One {#sec-one .chapter}\n\n"
                ":::: {#exr-e}\n"
                "{{< include /exercises/e.qmd >}}\n"
                "::::\n"
            ),
        )
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_exercise_labels(manifest, tmp_path) == []

    def test_exercise_with_extra_class_reports_nothing(self, base_manifest, tmp_path):
        """:::{#exr-e .exercise} is valid -- extra classes should not block the check."""
        _make_minimal_repo(
            tmp_path,
            chapter_text=(
                "# Chapter One {#sec-one .chapter}\n\n"
                "::::{#exr-e .exercise}\n"
                "{{< include /exercises/e.qmd >}}\n"
                "::::\n"
            ),
        )
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_exercise_labels(manifest, tmp_path) == []

    def test_exercise_not_in_any_div_reported(self, base_manifest, tmp_path):
        _make_minimal_repo(
            tmp_path,
            chapter_text=(
                "# Chapter One {#sec-one .chapter}\n\n"
                "{{< include /exercises/e.qmd >}}\n"
            ),
        )
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_exercise_labels(manifest, tmp_path)
        assert len(problems) == 1
        assert "e.qmd" in problems[0]
        assert "#exr-e" in problems[0]

    def test_exercise_in_wrong_exr_div_reported(self, base_manifest, tmp_path):
        """Include for 'e.qmd' wrapped in '#exr-other' -- label mismatch."""
        _make_minimal_repo(
            tmp_path,
            chapter_text=(
                "# Chapter One {#sec-one .chapter}\n\n"
                "::::{#exr-other}\n"
                "{{< include /exercises/e.qmd >}}\n"
                "::::\n"
            ),
        )
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_exercise_labels(manifest, tmp_path)
        assert len(problems) == 1
        assert "e.qmd" in problems[0]

    def test_exercise_in_non_exr_div_reported(self, base_manifest, tmp_path):
        """Inside a .theorem div with no #exr- label -- must be flagged."""
        _make_minimal_repo(
            tmp_path,
            chapter_text=(
                "# Chapter One {#sec-one .chapter}\n\n"
                ":::{.theorem}\n"
                "{{< include /exercises/e.qmd >}}\n"
                ":::\n"
            ),
        )
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_exercise_labels(manifest, tmp_path)
        assert len(problems) == 1

    def test_exercise_in_appendix_also_checked(self, base_manifest, tmp_path):
        _make_minimal_repo(
            tmp_path,
            appendix_text=(
                "# Appendix A {#sec-a}\n\n"
                "{{< include /exercises/e.qmd >}}\n"
            ),
        )
        manifest = NotesManifest.model_validate(base_manifest)
        problems = check_exercise_labels(manifest, tmp_path)
        assert len(problems) == 1
        assert "a.qmd" in problems[0]

    def test_exercise_include_inside_code_fence_not_flagged(self, base_manifest, tmp_path):
        """An include shown as an example inside a code block is not a real include."""
        _make_minimal_repo(
            tmp_path,
            chapter_text=(
                "# Chapter One {#sec-one .chapter}\n\n"
                "```\n"
                "{{< include /exercises/e.qmd >}}\n"
                "```\n"
            ),
        )
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_exercise_labels(manifest, tmp_path) == []

    def test_chapter_with_no_exercise_includes_reports_nothing(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        manifest = NotesManifest.model_validate(base_manifest)
        assert check_exercise_labels(manifest, tmp_path) == []


class TestRunAllChecks:
    def test_clean_repo_all_checks_empty(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path)
        manifest = NotesManifest.model_validate(base_manifest)
        results = run_all_checks(manifest, tmp_path)
        assert all(v == [] for v in results.values())

    def test_broken_repo_reports_under_correct_check_name(self, base_manifest, tmp_path):
        _make_minimal_repo(tmp_path, chapter_text="# Chapter One\n")
        manifest = NotesManifest.model_validate(base_manifest)
        results = run_all_checks(manifest, tmp_path)
        assert results["check_chapter_headings"] != []
        assert results["check_duplicate_labels"] == []
