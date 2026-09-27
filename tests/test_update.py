"""Tests for update.py steps 1-5.

Steps 6 (profiles), 7 (syllabus), 8 (lock), and 9 (commit) are not
implemented yet, so they're not tested here. What IS tested:

- Precondition guards (missing notes/, missing course/)
- toc.yml written as a side effect of step 1-2
- Validation abort: course/ is not touched if course.yml is invalid
  or if any A/B/C/D check fails
- unlock_course / lock_course chmod behaviour
- _is_excluded: exclusion rules for the copy step
- _copy_notes: chapter files are instrumented, others verbatim,
  excluded filenames/dirs are skipped
- Full integration: update() happy path
"""

import os
import stat

import pytest
import yaml

from coursecraft.update import (
    UpdateError,
    _is_excluded,
    _copy_notes,
    unlock_course,
    lock_course,
    update,
)
from coursecraft.manifest import NotesManifest
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _write_manifest(root: Path) -> None:
    (root / "coursecraft.yml").write_text(yaml.dump({
        "coursecraft_spec": "1.0",
        "conventions": {
            "chapter_glob": "chapters/*.qmd",
            "appendix_dir_glob": "appendices/*.qmd",
            "exercise_glob": "exercises/*.qmd",
            "insert_glob": "inserts/**/*.qmd",
        },
    }))


def _write_quarto_yml(root: Path, chapters=None, appendices=None) -> None:
    book: dict = {}
    if chapters is not None:
        book["chapters"] = chapters
    if appendices is not None:
        book["appendices"] = appendices
    (root / "_quarto.yml").write_text(yaml.dump({"book": book}))


def _make_notes(root: Path) -> None:
    """Minimal notes repo with one chapter (two labeled sections) and one exercise."""
    (root / "chapters").mkdir()
    (root / "chapters" / "ch1.qmd").write_text(
        "# Chapter One {#sec-ch1 .chapter}\n\n"
        "## Arguments {#sec-ch1-arguments}\n\nSome text.\n\n"
        "## Validity {#sec-ch1-validity}\n\nMore text.\n"
    )
    (root / "exercises").mkdir()
    (root / "exercises" / "ex1.qmd").write_text("An exercise.\n")
    _write_manifest(root)
    _write_quarto_yml(root, chapters=["index.qmd", "chapters/ch1.qmd"])


VALID_COURSE = {
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
            "exercises": ["ex1"],
        },
    ],
}


def _make_course(root: Path) -> None:
    """Minimal course/ directory (like what init creates, minus the git repo)."""
    root.mkdir(exist_ok=True)
    (root / "README.md").write_text("Generated.\n")
    (root / ".gitignore").write_text("_book/\n_site/\n.quarto/\n")


def _setup(tmp_path: Path):
    """Return (notes_root, course_path, course_yaml) all wired up and valid."""
    notes = tmp_path / "notes"
    notes.mkdir()
    _make_notes(notes)

    course = tmp_path / "course"
    _make_course(course)

    cy = tmp_path / "course.yml"
    cy.write_text(yaml.dump(VALID_COURSE))

    return notes, course, cy


# ---------------------------------------------------------------------------
# _is_excluded
# ---------------------------------------------------------------------------

class TestIsExcluded:
    def test_regular_chapter_not_excluded(self):
        assert not _is_excluded(Path("chapters/ch1.qmd"))

    def test_quarto_yml_not_excluded(self):
        assert not _is_excluded(Path("_quarto.yml"))

    def test_profile_file_excluded(self):
        assert _is_excluded(Path("_quarto-instructor.yml"))
        assert _is_excluded(Path("_quarto-lecture-01.yml"))

    def test_root_readme_excluded(self):
        assert _is_excluded(Path("README.md"))

    def test_nested_readme_not_excluded(self):
        # A README.md inside a subdirectory (unusual but possible) should pass
        assert not _is_excluded(Path("chapters/README.md"))

    def test_root_gitignore_excluded(self):
        assert _is_excluded(Path(".gitignore"))

    def test_root_coursecraft_yml_excluded(self):
        assert _is_excluded(Path("coursecraft.yml"))

    def test_root_index_qmd_excluded(self):
        assert _is_excluded(Path("index.qmd"))

    def test_ds_store_excluded_everywhere(self):
        assert _is_excluded(Path(".DS_Store"))
        assert _is_excluded(Path("chapters/.DS_Store"))

    def test_root_pre_commit_config_excluded(self):
        assert _is_excluded(Path(".pre-commit-config.yaml"))

    def test_exercise_file_not_excluded(self):
        assert not _is_excluded(Path("exercises/ex1.qmd"))

    def test_variables_yml_not_excluded(self):
        assert not _is_excluded(Path("_variables.yml"))


# ---------------------------------------------------------------------------
# lock_course / unlock_course
# ---------------------------------------------------------------------------

class TestChmodHelpers:
    def test_lock_makes_files_readonly(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        lock_course(tmp_path)
        assert not os.access(f, os.W_OK)

    def test_unlock_makes_files_writable(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        lock_course(tmp_path)
        unlock_course(tmp_path)
        assert os.access(f, os.W_OK)

    def test_unlock_is_noop_when_already_writable(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        unlock_course(tmp_path)   # already writable -- must not raise
        assert os.access(f, os.W_OK)

    def test_git_dir_contents_skipped(self, tmp_path):
        """Files inside .git/ must not be chmod'd -- git manages its own
        metadata and can't tolerate having it made read-only."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        git_file = git_dir / "config"
        git_file.write_text("[core]\n")
        original_mode = git_file.stat().st_mode

        lock_course(tmp_path)

        assert git_file.stat().st_mode == original_mode

    def test_recursive_into_subdirs(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "b.txt"
        f.write_text("y")
        lock_course(tmp_path)
        assert not os.access(f, os.W_OK)


# ---------------------------------------------------------------------------
# _copy_notes
# ---------------------------------------------------------------------------

class TestCopyNotes:
    def _manifest(self, root: Path) -> NotesManifest:
        return NotesManifest.from_yaml(root / "coursecraft.yml")

    def test_chapter_files_are_instrumented(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        copied = (course / "chapters" / "ch1.qmd").read_text()
        assert "content-hidden" in copied
        assert "sec-ch1-arguments" in copied

    def test_exercise_files_copied_verbatim(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        original = (notes / "exercises" / "ex1.qmd").read_text()
        copied = (course / "exercises" / "ex1.qmd").read_text()
        assert copied == original

    def test_quarto_yml_copied(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        assert (course / "_quarto.yml").exists()

    def test_index_qmd_not_copied(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        (notes / "index.qmd").write_text("# Preface\n")  # exists in notes
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        assert not (course / "index.qmd").exists()

    def test_readme_not_copied(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        (notes / "README.md").write_text("Notes repo readme.\n")
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        assert not (course / "README.md").exists()

    def test_coursecraft_yml_not_copied(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        assert not (course / "coursecraft.yml").exists()

    def test_profile_files_not_copied(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        (notes / "_quarto-instructor.yml").write_text("profile: instructor\n")
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        assert not (course / "_quarto-instructor.yml").exists()

    def test_book_dir_not_copied(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        book_dir = notes / "_book"
        book_dir.mkdir()
        (book_dir / "index.html").write_text("<html/>")
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        assert not (course / "_book").exists()

    def test_render_files_dir_not_copied(self, tmp_path):
        """Render artifact directories like ch1_files/ must be excluded."""
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        art_dir = notes / "ch1_files"
        art_dir.mkdir()
        (art_dir / "figure.png").write_bytes(b"\x89PNG")
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        assert not (course / "ch1_files").exists()

    def test_subdirectories_created(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        inserts = notes / "inserts" / "sub"
        inserts.mkdir(parents=True)
        (inserts / "i.qmd").write_text("Insert content.\n")
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        assert (course / "inserts" / "sub" / "i.qmd").exists()

    def test_appendix_files_are_instrumented(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        (notes / "appendices").mkdir()
        (notes / "appendices" / "app-a.qmd").write_text(
            "# Appendix A {#sec-app-a}\n\n"
            "## Proofs {#sec-app-a-proofs}\n\nProof text.\n"
        )
        (notes / "chapters").mkdir()
        (notes / "exercises").mkdir()
        _write_manifest(notes)
        _write_quarto_yml(notes,
                          chapters=[],
                          appendices=["appendices/app-a.qmd"])
        course = tmp_path / "course"
        course.mkdir()

        _copy_notes(notes, course, self._manifest(notes))

        copied = (course / "appendices" / "app-a.qmd").read_text()
        assert "content-hidden" in copied
        assert "sec-app-a-proofs" in copied


# ---------------------------------------------------------------------------
# update() integration
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_missing_notes_raises(self, tmp_path):
        _make_course(tmp_path / "course")
        (tmp_path / "course.yml").write_text(yaml.dump(VALID_COURSE))
        with pytest.raises(UpdateError, match="notes"):
            update(
                notes_dir=tmp_path / "notes",
                course_dir=tmp_path / "course",
                course_yaml=tmp_path / "course.yml",
                toc_out=tmp_path / "toc.yml",
            )

    def test_missing_course_raises(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        (tmp_path / "course.yml").write_text(yaml.dump(VALID_COURSE))
        with pytest.raises(UpdateError, match="init"):
            update(
                notes_dir=notes,
                course_dir=tmp_path / "course",
                course_yaml=tmp_path / "course.yml",
                toc_out=tmp_path / "toc.yml",
            )

    def test_missing_course_yaml_raises(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        _make_notes(notes)
        course = tmp_path / "course"
        _make_course(course)
        # course.yml intentionally not written
        with pytest.raises(UpdateError, match="course.yml"):
            update(
                notes_dir=notes,
                course_dir=course,
                course_yaml=tmp_path / "course.yml",
                toc_out=tmp_path / "toc.yml",
            )

    def test_invalid_course_yaml_raises(self, tmp_path):
        notes, course, cy = _setup(tmp_path)
        cy.write_text(yaml.dump({"course": {"title": "x"}}))  # missing notes_repo
        with pytest.raises(UpdateError, match="invalid"):
            update(
                notes_dir=notes, course_dir=course,
                course_yaml=cy, toc_out=tmp_path / "toc.yml",
            )

    def test_validation_failure_leaves_course_untouched(self, tmp_path):
        """A bad label in course.yml must abort before step 4 -- course/
        content must be identical before and after the failed update."""
        notes, course, cy = _setup(tmp_path)
        # Put a sentinel file in course/ to detect tampering
        sentinel = course / "sentinel.txt"
        sentinel.write_text("original")

        import copy as _copy
        bad_config = _copy.deepcopy(VALID_COURSE)
        bad_config["lectures"][0]["notes_end"] = "sec-ch1-ghost"
        cy.write_text(yaml.dump(bad_config))

        with pytest.raises(UpdateError, match="validation failed"):
            update(
                notes_dir=notes, course_dir=course,
                course_yaml=cy, toc_out=tmp_path / "toc.yml",
            )

        assert sentinel.read_text() == "original"
        assert not (course / "chapters").exists()

    def test_toc_yml_written(self, tmp_path):
        notes, course, cy = _setup(tmp_path)
        toc_out = tmp_path / "toc.yml"

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=toc_out)

        assert toc_out.exists()
        toc = yaml.safe_load(toc_out.read_text())
        assert len(toc["chapters"]) == 1
        assert toc["chapters"][0]["label"] == "sec-ch1"

    def test_chapter_files_instrumented_in_course(self, tmp_path):
        notes, course, cy = _setup(tmp_path)

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=tmp_path / "toc.yml")

        ch1 = (course / "chapters" / "ch1.qmd").read_text()
        assert "content-hidden" in ch1
        assert "sec-ch1-arguments" in ch1
        assert "sec-ch1-validity" in ch1

    def test_exercises_copied_verbatim(self, tmp_path):
        notes, course, cy = _setup(tmp_path)

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=tmp_path / "toc.yml")

        original = (notes / "exercises" / "ex1.qmd").read_text()
        assert (course / "exercises" / "ex1.qmd").read_text() == original

    def test_quarto_yml_present_in_course(self, tmp_path):
        notes, course, cy = _setup(tmp_path)

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=tmp_path / "toc.yml")

        assert (course / "_quarto.yml").exists()

    def test_index_qmd_not_copied_to_course(self, tmp_path):
        notes, course, cy = _setup(tmp_path)
        (notes / "index.qmd").write_text("# Preface\n")

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=tmp_path / "toc.yml")

        assert not (course / "index.qmd").exists()

    def test_excluded_metadata_not_in_course(self, tmp_path):
        notes, course, cy = _setup(tmp_path)
        (notes / ".github").mkdir()
        (notes / ".github" / "workflow.yml").write_text("on: push\n")
        (notes / "README.md").write_text("Notes readme.\n")

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=tmp_path / "toc.yml")

        assert not (course / ".github").exists()
        # course/ already had its own README.md from _make_course; the notes
        # README must not have overwritten it
        assert (course / "README.md").read_text() == "Generated.\n"

    def test_second_update_overwrites_first(self, tmp_path):
        """Running update twice on unchanged notes produces the same result."""
        notes, course, cy = _setup(tmp_path)
        toc_out = tmp_path / "toc.yml"

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=toc_out)
        first_content = (course / "chapters" / "ch1.qmd").read_text()

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=toc_out)
        second_content = (course / "chapters" / "ch1.qmd").read_text()

        assert first_content == second_content

    def test_adding_prose_to_notes_reflected_after_rerun(self, tmp_path):
        """Editing a chapter in notes/ between runs: the new prose must
        appear in course/ after the second update."""
        notes, course, cy = _setup(tmp_path)
        toc_out = tmp_path / "toc.yml"
        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=toc_out)

        # Add a sentence to the existing section
        ch = notes / "chapters" / "ch1.qmd"
        ch.write_text(ch.read_text() + "\nA new sentence added between runs.\n")

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=toc_out)

        assert "A new sentence added between runs." in (
            course / "chapters" / "ch1.qmd"
        ).read_text()

    def test_adding_labeled_section_to_notes_updates_toc_and_instruments(self, tmp_path):
        """Adding a new labeled ## section to notes/ between runs: toc.yml
        must gain the new entry, and the section must be instrumented in
        course/ even if course.yml doesn't yet reference it."""
        notes, course, cy = _setup(tmp_path)
        toc_out = tmp_path / "toc.yml"
        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=toc_out)

        ch = notes / "chapters" / "ch1.qmd"
        ch.write_text(ch.read_text() + "\n## A New Section {#sec-ch1-new}\n\nNew content.\n")

        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=toc_out)

        # toc.yml regenerated to include the new section
        toc = yaml.safe_load(toc_out.read_text())
        labels = [s["label"] for s in toc["chapters"][0]["sections"]]
        assert "sec-ch1-new" in labels

        # instrumented in course/ even though course.yml doesn't reference it
        copied = (course / "chapters" / "ch1.qmd").read_text()
        assert 'unless-meta="sections.sec-ch1-new"' in copied

    def test_renaming_label_in_notes_fails_check_a_on_rerun(self, tmp_path):
        """If a label referenced in course.yml is renamed in notes/, the
        second update must fail check A -- course/ must be left as-is from
        the first (valid) run."""
        notes, course, cy = _setup(tmp_path)
        toc_out = tmp_path / "toc.yml"
        update(notes_dir=notes, course_dir=course,
               course_yaml=cy, toc_out=toc_out)
        content_after_first = (course / "chapters" / "ch1.qmd").read_text()

        # Rename sec-ch1-arguments to sec-ch1-premises in notes/
        ch = notes / "chapters" / "ch1.qmd"
        ch.write_text(ch.read_text().replace(
            "{#sec-ch1-arguments}", "{#sec-ch1-premises}"
        ))

        # course.yml still references the old label -- must fail check A
        with pytest.raises(UpdateError, match="sec-ch1-arguments"):
            update(notes_dir=notes, course_dir=course,
                   course_yaml=cy, toc_out=toc_out)

        # course/ unchanged from the first valid run
        assert (course / "chapters" / "ch1.qmd").read_text() == content_after_first
