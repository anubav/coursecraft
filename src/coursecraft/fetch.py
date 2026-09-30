"""
coursecraft fetch-notes.

Clones a notes repo into ./notes, on a fresh section/<name> branch
(named after the current directory by default) -- never main, since
main now requires a pull request to merge into (see ARCHITECTURE.md).
The new branch is forked from the repo's default branch unless a
different source_branch is given (letting an instructor build off
their own long-lived branch of the notes repo instead), and is pushed
immediately, empty of section-specific commits, so two sections
created around the same time can't silently collide on the same
branch name; the collision is caught here instead of discovered later.
"""

import subprocess
from pathlib import Path
from typing import Optional

from ._gitutil import run_git, GitCommandError
from .manifest import NotesManifest, check_requires


def _install_pre_commit_hooks(target: Path) -> bool:
    """Run 'pre-commit install' in target if .pre-commit-config.yaml exists.

    Returns True if hooks were installed successfully, False if
    .pre-commit-config.yaml is absent, pre-commit isn't on PATH, or the
    command fails for any other reason. Never raises -- hook installation
    failure must not abort a successful clone."""
    if not (target / ".pre-commit-config.yaml").exists():
        return False
    try:
        result = subprocess.run(
            ["pre-commit", "install"],
            cwd=target,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


class FetchNotesError(Exception):
    pass


def _run(cmd: list[str], env: Optional[dict] = None) -> subprocess.CompletedProcess:
    try:
        return run_git(cmd, env=env)
    except GitCommandError as e:
        raise FetchNotesError(str(e)) from e


def branch_exists_on_remote(repo_url: str, branch: str) -> bool:
    """True if `branch` already exists as a head on the remote."""
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", repo_url, branch],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 2:
        return False
    raise FetchNotesError(
        f"could not query remote {repo_url!r}:\n{result.stderr.strip()}"
    )


def fetch_notes(
    repo_url: str,
    source_branch: Optional[str] = None,
    branch: Optional[str] = None,
    target_dir: str = "notes",
) -> tuple[Path, str]:
    """Clone repo_url into target_dir on a fresh branch, pushed
    immediately. source_branch is what to fork FROM (None = the
    repo's own default branch, typically main) -- distinct from
    `branch`, the new branch this section will push its own commits
    to. Raises FetchNotesError if target_dir already exists or the new
    branch name is already taken on the remote -- both refuse rather
    than silently reuse, matching init's own "error if already done"
    guard."""
    target = Path(target_dir)
    if target.exists():
        raise FetchNotesError(f"'{target}' already exists.")

    branch = branch or f"section/{Path.cwd().name}"

    if branch_exists_on_remote(repo_url, branch):
        raise FetchNotesError(f"branch '{branch}' already exists on {repo_url}.")

    clone_cmd = ["git", "clone"]
    if source_branch:
        clone_cmd += ["--branch", source_branch]
    clone_cmd += [repo_url, str(target)]
    _run(clone_cmd)

    _run(["git", "-C", str(target), "checkout", "-b", branch])
    _run(["git", "-C", str(target), "push", "-u", "origin", branch])

    manifest_path = target / "coursecraft.yml"
    if manifest_path.exists():
        try:
            manifest = NotesManifest.from_yaml(manifest_path)
            if manifest.requires:
                check_requires(manifest.requires)
        except ValueError as e:
            raise FetchNotesError(str(e)) from e

    _install_pre_commit_hooks(target)

    return target, branch
