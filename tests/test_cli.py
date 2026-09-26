import sys
from unittest.mock import patch, MagicMock

import pytest
import yaml

from coursecraft.cli import main
from coursecraft.fetch import FetchNotesError


def run_cli(argv, monkeypatch):
    """Invoke main() with the given argv (excluding the program name),
    return its exit code. main() always calls sys.exit(...), so every
    invocation raises SystemExit -- that's the contract being tested,
    not an accident to work around."""
    monkeypatch.setattr(sys, 'argv', ['coursecraft'] + argv)
    with pytest.raises(SystemExit) as exc_info:
        main()
    return exc_info.value.code


class TestReflowCLI:
    def test_writes_changes_and_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        """Non-check mode still exits 1 when something needed
        reflowing -- this is what makes the pre-commit hook stop a
        commit for review; it's not a bug that non-check mode isn't 0."""
        f = tmp_path / "test.qmd"
        f.write_text("First sentence. Second sentence.\n")

        code = run_cli(['reflow', str(f)], monkeypatch)

        assert code == 1
        assert f.read_text() == "First sentence.\nSecond sentence.\n"
        assert 'reflowed' in capsys.readouterr().out

    def test_exits_zero_when_already_formatted(self, tmp_path, monkeypatch):
        f = tmp_path / "test.qmd"
        f.write_text("First sentence.\nSecond sentence.\n")
        code = run_cli(['reflow', str(f)], monkeypatch)
        assert code == 0

    def test_check_mode_does_not_write(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "test.qmd"
        original = "First sentence. Second sentence.\n"
        f.write_text(original)

        code = run_cli(['reflow', '--check', str(f)], monkeypatch)

        assert code == 1
        assert f.read_text() == original  # untouched
        assert 'would be reflowed' in capsys.readouterr().out

    def test_width_flag_reaches_real_reflow(self, tmp_path, monkeypatch):
        """Confirms --width actually threads through to column-wrap
        mode, not just that the flag is accepted by argparse."""
        f = tmp_path / "test.qmd"
        f.write_text("word " * 30 + "\n")

        run_cli(['reflow', '--width', '20', str(f)], monkeypatch)

        lines = f.read_text().strip().split('\n')
        assert len(lines) > 1  # actually wrapped, not one giant line
        assert all(len(l) <= 25 for l in lines)  # some slack, not exact

    def test_multiple_paths_all_processed(self, tmp_path, monkeypatch):
        f1 = tmp_path / "a.qmd"
        f2 = tmp_path / "b.qmd"
        f1.write_text("One sentence. Two sentences.\n")
        f2.write_text("Three sentences. Four sentences.\n")

        run_cli(['reflow', str(f1), str(f2)], monkeypatch)

        assert f1.read_text() == "One sentence.\nTwo sentences.\n"
        assert f2.read_text() == "Three sentences.\nFour sentences.\n"


class TestLintCLI:
    def test_no_violations_exits_zero(self, tmp_path, monkeypatch):
        f = tmp_path / "test.qmd"
        f.write_text("## Labeled {#sec-x}\n")
        assert run_cli(['lint', str(f)], monkeypatch) == 0

    def test_violations_exit_one_and_are_printed(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "test.qmd"
        f.write_text("## Unlabeled\n")

        code = run_cli(['lint', str(f)], monkeypatch)

        assert code == 1
        out = capsys.readouterr().out
        assert 'Unlabeled' in out
        assert 'no {#sec-...} label' in out


class TestValidateCLI:
    VALID = {
        "course": {"title": "x", "notes_repo": "https://example.com/n.git"},
        "section": {
            "instructor": "a", "course_number": "b", "term": "c", "location": "d",
            "meeting_times": "e", "start_date": "2026-01-01", "end_date": "2026-06-01",
        },
    }

    def test_valid_file_exits_zero(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "course.yaml"
        f.write_text(yaml.dump(self.VALID))

        code = run_cli(['validate', str(f)], monkeypatch)

        assert code == 0
        assert 'OK' in capsys.readouterr().out

    def test_invalid_file_exits_one(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "course.yaml"
        f.write_text(yaml.dump({"course": {"title": "x"}}))  # missing notes_repo

        code = run_cli(['validate', str(f)], monkeypatch)

        assert code == 1
        out = capsys.readouterr().out
        assert 'INVALID' in out


class TestValidateNotesCLI:
    def _make_minimal_repo(self, root):
        (root / "chapters").mkdir()
        (root / "chapters" / "one.qmd").write_text(
            "# Chapter One {#sec-one .chapter}\n"
        )
        (root / "appendices").mkdir()
        (root / "appendices" / "a.qmd").write_text(
            "# Appendix A {#sec-a .appendix}\n"
        )
        (root / "exercises").mkdir()
        (root / "exercises" / "e.qmd").write_text("An exercise.\n")
        (root / "inserts" / "sub").mkdir(parents=True)
        (root / "inserts" / "sub" / "i.qmd").write_text("An insert.\n")
        (root / "coursecraft.yml").write_text(yaml.dump({
            "coursecraft_spec": "1.0",
            "conventions": {
                "chapter_glob": "chapters/*.qmd",
                "appendix_dir_glob": "appendices/*.qmd",
                "exercise_glob": "exercises/*.qmd",
                "insert_glob": "inserts/**/*.qmd",
            },
        }))

    def test_defaults_to_current_directory(self, tmp_path, monkeypatch, capsys):
        self._make_minimal_repo(tmp_path)
        monkeypatch.chdir(tmp_path)

        code = run_cli(['validate-notes'], monkeypatch)

        assert code == 0
        assert 'OK' in capsys.readouterr().out

    def test_explicit_path_respected(self, tmp_path, monkeypatch):
        self._make_minimal_repo(tmp_path)
        assert run_cli(['validate-notes', str(tmp_path)], monkeypatch) == 0

    def test_missing_manifest_exits_one(self, tmp_path, monkeypatch, capsys):
        code = run_cli(['validate-notes', str(tmp_path)], monkeypatch)
        assert code == 1
        assert 'not found' in capsys.readouterr().out

    def test_invalid_manifest_exits_one(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "coursecraft.yml").write_text(
            yaml.dump({"coursecraft_spec": "99.0", "conventions": {}})
        )
        code = run_cli(['validate-notes', str(tmp_path)], monkeypatch)
        assert code == 1
        assert 'INVALID' in capsys.readouterr().out

    def test_failing_content_checks_exit_one(self, tmp_path, monkeypatch, capsys):
        self._make_minimal_repo(tmp_path)
        # introduce a real problem: a duplicate label across two files
        (tmp_path / "chapters" / "one.qmd").write_text(
            "# Chapter One {#sec-a .chapter}\n"  # collides with appendices/a.qmd's sec-a
        )
        code = run_cli(['validate-notes', str(tmp_path)], monkeypatch)
        assert code == 1
        assert 'check_duplicate_labels' in capsys.readouterr().out


class TestFetchNotesCLI:
    """Mocks fetch_notes specifically -- the one subcommand where real
    execution would mean real network calls. Everything else about
    the wiring (course.yaml parsing, argument threading, error
    reporting) is exercised for real."""

    VALID_COURSE = {"course": {"title": "x", "notes_repo": "https://example.com/n.git"}}

    def test_missing_course_yaml_exits_one_with_short_message(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        code = run_cli(['fetch-notes'], monkeypatch)
        assert code == 1
        assert capsys.readouterr().out.strip() == (
            'fetch-notes failed: no course.yaml found in the current directory.'
        )

    def test_invalid_course_yaml_exits_one(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course.yaml").write_text(yaml.dump({"course": {"title": "x"}}))
        code = run_cli(['fetch-notes'], monkeypatch)
        assert code == 1
        assert 'INVALID' in capsys.readouterr().out

    def test_calls_fetch_notes_with_repo_and_branch_from_yaml(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        data = {"course": {
            "title": "x", "notes_repo": "https://example.com/n.git",
            "notes_branch": "kevin-custom",
        }}
        (tmp_path / "course.yaml").write_text(yaml.dump(data))

        with patch('coursecraft.cli.fetch_notes') as mock_fetch:
            mock_fetch.return_value = (tmp_path / "notes", "section/x")
            run_cli(['fetch-notes'], monkeypatch)

        mock_fetch.assert_called_once_with(
            repo_url="https://example.com/n.git",
            source_branch="kevin-custom",
            branch=None,
            target_dir="notes",
        )

    def test_branch_and_target_flags_threaded_through(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course.yaml").write_text(yaml.dump(self.VALID_COURSE))

        with patch('coursecraft.cli.fetch_notes') as mock_fetch:
            mock_fetch.return_value = (tmp_path / "custom", "section/mine")
            run_cli(
                ['fetch-notes', '--branch', 'section/mine', '--target', 'custom'],
                monkeypatch,
            )

        _, kwargs = mock_fetch.call_args
        assert kwargs['branch'] == 'section/mine'
        assert kwargs['target_dir'] == 'custom'

    def test_underlying_fetch_error_reported_and_exits_one(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course.yaml").write_text(yaml.dump(self.VALID_COURSE))

        with patch('coursecraft.cli.fetch_notes') as mock_fetch:
            mock_fetch.side_effect = FetchNotesError("'notes' already exists.")
            code = run_cli(['fetch-notes'], monkeypatch)

        assert code == 1
        assert "fetch-notes failed: 'notes' already exists." in capsys.readouterr().out

    def test_skips_validate_notes_if_no_manifest(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course.yaml").write_text(yaml.dump(self.VALID_COURSE))
        cloned = tmp_path / "notes"
        cloned.mkdir()

        with patch('coursecraft.cli.fetch_notes') as mock_fetch:
            mock_fetch.return_value = (cloned, "section/x")
            code = run_cli(['fetch-notes'], monkeypatch)

        assert code == 0
        assert 'skipping validate-notes' in capsys.readouterr().out

    def test_runs_validate_notes_after_successful_clone(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course.yaml").write_text(yaml.dump(self.VALID_COURSE))
        cloned = tmp_path / "notes"
        cloned.mkdir()
        TestValidateNotesCLI()._make_minimal_repo(cloned)  # reuse the fixture repo

        with patch('coursecraft.cli.fetch_notes') as mock_fetch:
            mock_fetch.return_value = (cloned, "section/x")
            code = run_cli(['fetch-notes'], monkeypatch)

        assert code == 0
        assert 'validate-notes: OK' in capsys.readouterr().out


class TestInitCLI:
    """Real execution -- init is local-only, no network, and already
    thoroughly covered at the library level; these tests are purely
    about the CLI wiring on top of it."""

    def test_creates_course_and_yaml_exits_zero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        code = run_cli(['init', 'https://example.com/notes.git'], monkeypatch)
        assert code == 0
        out = capsys.readouterr().out
        assert "Created 'course'" in out
        assert 'Created course.yaml' in out
        assert (tmp_path / "course").is_dir()

    def test_existing_course_dir_exits_one(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course").mkdir()
        code = run_cli(['init', 'https://example.com/notes.git'], monkeypatch)
        assert code == 1
        assert "already exists" in capsys.readouterr().out

    def test_notes_branch_flag_threaded_through(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run_cli(
            ['init', 'https://example.com/notes.git', '--notes-branch', 'kevin-custom'],
            monkeypatch,
        )
        data = yaml.safe_load((tmp_path / "course.yaml").read_text())
        assert data['course']['notes_branch'] == 'kevin-custom'

    def test_existing_course_yaml_message(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course.yaml").write_text("course:\n  title: real\n")

        code = run_cli(['init', 'https://example.com/notes.git'], monkeypatch)

        assert code == 0
        assert 'course.yaml already exists' in capsys.readouterr().out
