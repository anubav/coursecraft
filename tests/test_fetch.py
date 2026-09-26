from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from coursecraft.fetch import fetch_notes, branch_exists_on_remote, FetchNotesError


class TestBranchExistsOnRemote:
    def test_returncode_0_with_output_means_exists(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="abc123\trefs/heads/main\n", stderr=""
            )
            assert branch_exists_on_remote("https://example.com/repo.git", "main") is True

    def test_returncode_2_means_does_not_exist(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="")
            assert branch_exists_on_remote("https://example.com/repo.git", "nope") is False

    def test_other_returncode_raises(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="fatal: could not resolve host"
            )
            with pytest.raises(FetchNotesError, match="could not query remote"):
                branch_exists_on_remote("https://example.com/repo.git", "main")


class TestFetchNotes:
    def test_refuses_existing_target_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "notes").mkdir()
        with pytest.raises(FetchNotesError, match="already exists"):
            fetch_notes("https://example.com/repo.git")

    def test_refuses_existing_remote_branch(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("coursecraft.fetch.branch_exists_on_remote", return_value=True):
            with pytest.raises(FetchNotesError, match="already exists on"):
                fetch_notes("https://example.com/repo.git", branch="section/taken")

    def test_default_branch_name_uses_cwd_with_section_prefix(self, tmp_path, monkeypatch):
        section_dir = tmp_path / "my-cool-section"
        section_dir.mkdir()
        monkeypatch.chdir(section_dir)

        with patch("coursecraft.fetch.branch_exists_on_remote", return_value=False), \
             patch("coursecraft.fetch._run") as mock_run:
            target, branch = fetch_notes("https://example.com/repo.git")

        assert branch == "section/my-cool-section"
        assert target == Path("notes")

    def test_explicit_branch_name_overrides_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("coursecraft.fetch.branch_exists_on_remote", return_value=False), \
             patch("coursecraft.fetch._run") as mock_run:
            _, branch = fetch_notes("https://example.com/repo.git", branch="section/custom")
        assert branch == "section/custom"

    def test_runs_clone_checkout_and_push_in_order(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("coursecraft.fetch.branch_exists_on_remote", return_value=False), \
             patch("coursecraft.fetch._run") as mock_run:
            fetch_notes("https://example.com/repo.git", branch="section/x")

        calls = [call.args[0] for call in mock_run.call_args_list]
        assert calls[0] == ["git", "clone", "https://example.com/repo.git", "notes"]
        assert calls[1] == ["git", "-C", "notes", "checkout", "-b", "section/x"]
        assert calls[2] == ["git", "-C", "notes", "push", "-u", "origin", "section/x"]

    def test_source_branch_included_in_clone_command(self, tmp_path, monkeypatch):
        """A source_branch (e.g. an instructor's own long-lived branch
        of the notes repo, not main) must be passed to git clone --
        confirmed separately that this still fetches every other
        branch too, not just the one checked out."""
        monkeypatch.chdir(tmp_path)
        with patch("coursecraft.fetch.branch_exists_on_remote", return_value=False), \
             patch("coursecraft.fetch._run") as mock_run:
            fetch_notes(
                "https://example.com/repo.git",
                source_branch="kevin-custom",
                branch="section/x",
            )
        calls = [call.args[0] for call in mock_run.call_args_list]
        assert calls[0] == [
            "git", "clone", "--branch", "kevin-custom",
            "https://example.com/repo.git", "notes",
        ]

    def test_no_source_branch_omits_branch_flag(self, tmp_path, monkeypatch):
        """None means 'the repo's own default branch' -- must not pass
        an empty --branch flag or similar."""
        monkeypatch.chdir(tmp_path)
        with patch("coursecraft.fetch.branch_exists_on_remote", return_value=False), \
             patch("coursecraft.fetch._run") as mock_run:
            fetch_notes("https://example.com/repo.git", branch="section/x")
        calls = [call.args[0] for call in mock_run.call_args_list]
        assert "--branch" not in calls[0]

    def test_custom_target_dir_respected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("coursecraft.fetch.branch_exists_on_remote", return_value=False), \
             patch("coursecraft.fetch._run") as mock_run:
            target, _ = fetch_notes(
                "https://example.com/repo.git", branch="section/x", target_dir="custom-notes"
            )
        assert target == Path("custom-notes")
        calls = [call.args[0] for call in mock_run.call_args_list]
        assert calls[0][-1] == "custom-notes"

    def test_underlying_command_failure_raises_fetch_notes_error(self, tmp_path, monkeypatch):
        """_run itself (unmocked here) must translate a real subprocess
        failure into FetchNotesError, not let a raw CalledProcessError
        or silent wrong-exit-code slip through."""
        monkeypatch.chdir(tmp_path)
        with patch("coursecraft.fetch.branch_exists_on_remote", return_value=False), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="fatal: repository not found"
            )
            with pytest.raises(FetchNotesError, match="command failed"):
                fetch_notes("https://example.com/does-not-exist.git", branch="section/x")
