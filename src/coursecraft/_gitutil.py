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

import itertools
import subprocess
import sys
import threading
import time
from typing import Optional


class GitCommandError(Exception):
    pass


def run_git(cmd: list[str], env: Optional[dict] = None) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise GitCommandError(
            f"command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result


def run_git_with_spinner(
    cmd: list[str],
    message: str,
    env: Optional[dict] = None,
    runner=run_git,
) -> subprocess.CompletedProcess:
    """Like run_git, but shows a cycling-ellipsis progress indicator on
    the same line while cmd runs in the background -- a clone can take
    a while with no other output, and this is just so it doesn't look
    hung. `runner` defaults to run_git, but callers that wrap it in
    their own exception type (e.g. fetch.py's _run -> FetchNotesError)
    should pass that wrapper instead, so a caller mocking their own
    module-level runner still intercepts this path -- confirmed by a
    real regression this caught: without this, mocking fetch._run
    didn't stop the actual `git clone` from running, since this
    function was calling run_git directly instead."""
    outcome: dict = {}

    def target():
        try:
            outcome['result'] = runner(cmd, env=env)
        except Exception as e:
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
