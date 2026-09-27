"""
Shared subprocess-running helpers for git operations.

Extracted out of fetch.py and init.py, which had each grown their own
near-identical _run helper -- worth doing once, here, before update.py
and deploy.py (which need the exact same pattern) would otherwise
duplicate it a third and fourth time. Callers keep their own,
command-specific exception types (FetchNotesError, InitError, ...) by
catching GitCommandError and re-raising -- this file doesn't know or
care which command is calling it.
"""

import os
import subprocess
from typing import Optional


class GitCommandError(Exception):
    pass


def coursecraft_env() -> dict:
    """Environment for coursecraft's own git commits in course/.

    Sets COURSECRAFT_INTERNAL=1 (required by the pre-commit hook that
    guards course/ against hand-editing) and a consistent machine identity
    so CI runners don't need git user.name / user.email configured."""
    return {
        **os.environ,
        "COURSECRAFT_INTERNAL": "1",
        "GIT_AUTHOR_NAME": "coursecraft",
        "GIT_AUTHOR_EMAIL": "coursecraft@localhost",
        "GIT_COMMITTER_NAME": "coursecraft",
        "GIT_COMMITTER_EMAIL": "coursecraft@localhost",
    }


def run_git(cmd: list[str], env: Optional[dict] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise GitCommandError(
            f"command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result
