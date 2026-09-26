import subprocess

import pytest
import yaml

from coursecraft.init import init, InitError
from coursecraft.schema import CourseConfig
from pydantic import ValidationError


def _git(args, cwd, env=None):
    return subprocess.run(
        ["git", "-C", str(cwd)] + args,
        capture_output=True, text=True, env=env,
    )


class TestCourseDirCreation:
    def test_creates_course_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        init("https://example.com/notes.git")
        assert (tmp_path / "course").is_dir()

    def test_course_dir_is_a_git_repo_on_main(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        course_path, _ = init("https://example.com/notes.git")
        result = _git(["branch"], course_path)
        assert "* main" in result.stdout

    def test_initial_commit_made(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        course_path, _ = init("https://example.com/notes.git")
        result = _git(["log", "--oneline"], course_path)
        assert result.returncode == 0
        assert len(result.stdout.strip().split("\n")) == 1

    def test_gitignore_and_readme_written(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        course_path, _ = init("https://example.com/notes.git")
        assert (course_path / ".gitignore").exists()
        assert (course_path / "README.md").exists()
        assert "_book" in (course_path / ".gitignore").read_text()

    def test_refuses_existing_course_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course").mkdir()
        with pytest.raises(InitError, match="already exists"):
            init("https://example.com/notes.git")

    def test_custom_course_dir_respected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        course_path, _ = init(
            "https://example.com/notes.git", course_dir="my-course"
        )
        assert course_path.name == "my-course"
        assert (tmp_path / "my-course").is_dir()


class TestPreCommitHookReallyBlocks:
    """Not mocked -- these actually run git and confirm the hook binary
    behavior, since a hook that looks right on paper but has the wrong
    shebang, permissions, or env-var logic would only be caught this way."""

    def test_manual_commit_without_env_var_is_rejected(self, tmp_path, monkeypatch):
        import os
        monkeypatch.chdir(tmp_path)
        course_path, _ = init("https://example.com/notes.git")

        (course_path / "sneaky.txt").write_text("hand-edited")
        # identity provided (isolating exactly the hook's own check --
        # without this, git could reject the commit for a different
        # reason first, on a machine/CI runner with no global identity)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "someone", "GIT_AUTHOR_EMAIL": "someone@example.com",
            "GIT_COMMITTER_NAME": "someone", "GIT_COMMITTER_EMAIL": "someone@example.com",
        }
        _git(["add", "-A"], course_path, env=env)
        result = _git(["commit", "-m", "sneaky manual commit"], course_path, env=env)

        assert result.returncode != 0
        assert "not allowed" in result.stdout + result.stderr

    def test_commit_with_internal_env_var_succeeds(self, tmp_path, monkeypatch):
        import os
        monkeypatch.chdir(tmp_path)
        course_path, _ = init("https://example.com/notes.git")

        (course_path / "generated.txt").write_text("from coursecraft")
        env = {
            **os.environ,
            "COURSECRAFT_INTERNAL": "1",
            "GIT_AUTHOR_NAME": "coursecraft", "GIT_AUTHOR_EMAIL": "coursecraft@localhost",
            "GIT_COMMITTER_NAME": "coursecraft", "GIT_COMMITTER_EMAIL": "coursecraft@localhost",
        }
        _git(["add", "-A"], course_path, env=env)
        result = _git(["commit", "-m", "generated commit"], course_path, env=env)

        assert result.returncode == 0

    def test_hook_file_is_executable(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        course_path, _ = init("https://example.com/notes.git")
        hook = course_path / ".git" / "hooks" / "pre-commit"
        assert hook.stat().st_mode & 0o111  # some execute bit set


class TestCourseYamlScaffolding:
    def test_creates_course_yaml_with_real_repo_and_placeholders(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        init("https://example.com/notes.git")
        data = yaml.safe_load((tmp_path / "course.yaml").read_text())
        assert data["course"]["notes_repo"] == "https://example.com/notes.git"
        assert data["course"]["title"] == "REPLACE_ME"
        assert data["section"]["start_date"] == "REPLACE_ME"
        assert data["lectures"] == []
        assert data["assignments"] == []

    def test_notes_branch_included_when_given(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        init("https://example.com/notes.git", notes_branch="kevin-custom")
        data = yaml.safe_load((tmp_path / "course.yaml").read_text())
        assert data["course"]["notes_branch"] == "kevin-custom"

    def test_notes_branch_omitted_when_not_given(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        init("https://example.com/notes.git")
        data = yaml.safe_load((tmp_path / "course.yaml").read_text())
        assert "notes_branch" not in data["course"]

    def test_existing_course_yaml_never_overwritten(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        original = "course:\n  title: My Real Course\n  notes_repo: real.git\n"
        (tmp_path / "course.yaml").write_text(original)

        _, wrote_yaml = init("https://example.com/notes.git")

        assert wrote_yaml is False
        assert (tmp_path / "course.yaml").read_text() == original

    def test_course_yaml_not_created_if_course_dir_already_exists(
        self, tmp_path, monkeypatch
    ):
        """Ordering guard: course_dir is checked first, so a failed
        init (course/ already there) must never leave a stray
        scaffolded course.yaml as a side effect."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "course").mkdir()
        with pytest.raises(InitError):
            init("https://example.com/notes.git")
        assert not (tmp_path / "course.yaml").exists()

    def test_scaffolded_yaml_fails_real_validation_due_to_placeholders(
        self, tmp_path, monkeypatch
    ):
        """Ties init's output directly to schema.py: confirms the
        REPLACE_ME placeholders actually fail CourseConfig validation
        (bad date format) rather than just asserting they look wrong."""
        monkeypatch.chdir(tmp_path)
        init("https://example.com/notes.git")
        with pytest.raises(ValidationError):
            CourseConfig.from_yaml(tmp_path / "course.yaml")
