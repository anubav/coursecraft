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

import itertools
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional


class FetchNotesError(Exception):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FetchNotesError(
            f"command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result


def _run_with_spinner(cmd: list[str], message: str) -> subprocess.CompletedProcess:
    """Like _run, but shows a cycling-ellipsis progress indicator on
    the same line while cmd runs in the background -- a clone can take
    a while with no other output, and this is just so it doesn't look
    hung. Purely cosmetic: the actual work and error handling are
    still done by _run, called from a background thread."""
    outcome: dict = {}

    def target():
        try:
            outcome['result'] = _run(cmd)
        except FetchNotesError as e:
            outcome['error'] = e

    thread = threading.Thread(target=target)
    thread.start()

    dots_cycle = itertools.cycle(['', '.', '..', '...'])
    max_width = len(message) + 3
    while thread.is_alive():
        line = f'{message}{next(dots_cycle)}'
        sys.stdout.write('\r' + line.ljust(max_width))
        sys.stdout.flush()
        time.sleep(0.4)
    thread.join()
    sys.stdout.write('\r' + ' ' * max_width + '\r')
    sys.stdout.flush()

    if 'error' in outcome:
        raise outcome['error']
    return outcome['result']


def branch_exists_on_remote(repo_url: str, branch: str) -> bool:
    """True if `branch` already exists as a head on the remote."""
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", repo_url, branch],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return bool(result.stdout.strip())
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
    _run_with_spinner(clone_cmd, "Fetching notes")

    _run(["git", "-C", str(target), "checkout", "-b", branch])
    _run(["git", "-C", str(target), "push", "-u", "origin", branch])

    return target, branch
