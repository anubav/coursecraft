"""
coursecraft update -- all ten steps.

The ten-step flow:
  1. Build toc by scanning notes/ directly (never reads toc.yml off disk)
  2. Write toc.yml as a side effect of step 1
  3. Validate course.yml against notes/ (A/B/C) -- abort if invalid,
     course/ must not be touched at all while the config is broken
  4. Unlock course/ (undo the read-only chmod from the previous run --
     no-op on first update since files are already writable)
  5. Copy notes/ -> course/, instrumenting chapter/appendix .qmd files
     in-flight; everything else copied verbatim
  5b. Strip chapters/appendices from base _quarto.yml so profiles own
     the chapter list
  6. Generate hw-NN.qmd / exam-NN.qmd (and *-solutions.qmd) in course/
  7. Generate Quarto profile YAMLs (_quarto-<date>.yml) in course/
  8. Generate syllabus (course/index.qmd)
  8b. Write coursecraft-manifest.json (date -> start label, for CI redirect)
  9. Lock course/ (chmod 0o444 -- local safeguard against hand-editing;
     does not survive a git clone, so it doesn't affect CI)
 10. Commit course/
 11. (optional) Push course/ to its remote
"""

import json
import os
import re
import shutil
from pathlib import Path

import yaml
from pydantic import ValidationError

from ._gitutil import run_git, GitCommandError, coursecraft_env
from .course_checks import run_course_checks
from .hw import generate_homework_files
from .instrument import instrument
from .manifest import NotesManifest
from .profiles import generate_profiles
from .schema import CourseConfig
from .syllabus import generate_syllabus
from .toc import build_toc, write_toc_yaml, TocError


class UpdateError(Exception):
    pass


def _git(cmd: list[str], env: dict | None = None) -> None:
    try:
        run_git(cmd, env=env)
    except GitCommandError as e:
        raise UpdateError(str(e)) from e


def _write_course_manifest(config: CourseConfig, course_path: Path) -> None:
    """Write coursecraft-manifest.json mapping each lecture date to its
    first section label. The CI deploy workflow reads this to anchor the
    landing-page redirect to the first section of the current lecture."""
    data = {
        lec.date.isoformat(): lec.sections[0]
        for lec in config.lectures
        if lec.sections
    }
    (course_path / "coursecraft-manifest.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _commit_course(course_path: Path) -> None:
    """Stage all changes in course/ and commit if anything is staged.

    Uses coursecraft_env() so the pre-commit hook (which guards against
    hand-editing) allows the commit through. Skips the commit entirely
    when notes and course.yml haven't changed since the last run."""
    env = coursecraft_env()
    _git(["git", "-C", str(course_path), "add", "-A"], env=env)
    try:
        # exit 0 → nothing staged; exit 1 → staged changes exist
        run_git(["git", "-C", str(course_path), "diff", "--cached", "--quiet"])
        return  # nothing to commit
    except GitCommandError:
        pass
    _git(
        ["git", "-C", str(course_path), "commit", "-m", "coursecraft update"],
        env=env,
    )


# ---------------------------------------------------------------------------
# Exclusions for the notes/ -> course/ copy
# ---------------------------------------------------------------------------

# Directories that should never be descended into
_EXCLUDE_DIRS = frozenset({
    ".git",
    "_book", "_site", ".quarto",   # render output / cache
    ".github",                      # CI workflows for the notes repo
})

# Files excluded only when they appear at the notes root -- they either
# belong to the notes repo itself (README, .gitignore, coursecraft.yml,
# .pre-commit-config.yaml) or are generated fresh by a later update step
# (index.qmd by the syllabus generator, step 8).
_EXCLUDE_ROOT_FILES = frozenset({
    "README.md",
    ".gitignore",
    "coursecraft.yml",
    ".pre-commit-config.yaml",
    "index.qmd",
})

# Files excluded wherever they appear
_EXCLUDE_ANYWHERE = frozenset({".DS_Store"})

# _quarto-<something>.yml are profile files; the base _quarto.yml (no
# hyphen) is not matched and IS copied -- it carries format/theme settings
# that the generated profiles inherit.
_PROFILE_RE = re.compile(r"^_quarto-.+\.yml$")


def _is_excluded(rel: Path) -> bool:
    """True if this notes-relative path should be skipped during copy."""
    name = rel.name
    if name in _EXCLUDE_ANYWHERE:
        return True
    if _PROFILE_RE.match(name):
        return True
    if rel.parent == Path(".") and name in _EXCLUDE_ROOT_FILES:
        return True
    return False


# ---------------------------------------------------------------------------
# Lock / unlock
# ---------------------------------------------------------------------------

def _chmod_tree(path: Path, mode: int) -> None:
    """Recursively set mode on every *file* under path, skipping .git/
    and its contents at every level (git must manage its own metadata)."""
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            (Path(dirpath) / name).chmod(mode)


def unlock_course(course_path: Path) -> None:
    """Make every file in course/ writable. Safe no-op on first update."""
    _chmod_tree(course_path, 0o644)


def lock_course(course_path: Path) -> None:
    """Make every file in course/ read-only. Local safeguard against
    accidental hand-editing; the permission does not survive a git clone."""
    _chmod_tree(course_path, 0o444)


# ---------------------------------------------------------------------------
# Copy + instrument (step 5)
# ---------------------------------------------------------------------------

def _strip_quarto_chapter_lists(course_path: Path, title: str | None = None) -> None:
    """Strip all chapters (except index.qmd) and appendices from the
    _quarto.yml that was just copied into course/. Also sets book.title
    to the section-specific course title when provided, and removes author."""
    quarto_yml = course_path / "_quarto.yml"
    if not quarto_yml.exists():
        return
    data = yaml.safe_load(quarto_yml.read_text(encoding="utf-8")) or {}
    book = data.setdefault("book", {})
    book["chapters"] = ["index.qmd"]
    book.pop("appendices", None)
    book.pop("author", None)
    if title:
        book["title"] = title
    quarto_yml.write_text(
        yaml.dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _copy_notes(notes_root: Path, course_path: Path, manifest: NotesManifest) -> None:
    """Copy notes_root -> course_path.

    Chapter and appendix files (matched by the manifest's globs) are
    instrumented in-flight: every labeled ## section gets wrapped in a
    content-hidden div keyed on sections.<label>, ready for the profile
    YAML to show or hide. Everything else is copied verbatim. Excluded
    paths (render artifacts, notes-repo metadata, step-7-generated files)
    are skipped entirely."""
    conv = manifest.conventions
    instrument_files = (
        set(notes_root.glob(conv.chapter_glob))
        | set(notes_root.glob(conv.appendix_dir_glob))
    )

    for dirpath, dirnames, filenames in os.walk(notes_root):
        current = Path(dirpath)
        # Prune excluded dirs and render-artifact dirs (*_files) in-place
        # so os.walk never descends into them.
        dirnames[:] = [
            d for d in dirnames
            if d not in _EXCLUDE_DIRS and not d.endswith("_files")
        ]

        for name in filenames:
            src = current / name
            rel = src.relative_to(notes_root)
            if _is_excluded(rel):
                continue

            dst = course_path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)

            if src in instrument_files:
                dst.write_text(
                    instrument(src.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )
            else:
                shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def update(
    notes_dir: str | Path = "notes",
    course_dir: str | Path = "course",
    course_yaml: str | Path = "course.yml",
    toc_out: str | Path = "toc.yml",
    push: bool = False,
    lock: bool = True,
) -> None:
    """Run all update steps, optionally skipping the read-only lock and/or pushing.

    Raises UpdateError for any condition that should abort the run --
    missing directories, invalid course.yml, failed validation checks.
    course/ is never modified when validation fails (step 3 aborts before
    step 4 unlocks anything)."""
    notes_root = Path(notes_dir)
    course_path = Path(course_dir)

    if not notes_root.is_dir():
        raise UpdateError(f"'{notes_root}' not found.")
    if not course_path.is_dir():
        raise UpdateError(
            f"'{course_path}' not found -- run 'coursecraft init' first."
        )

    # Steps 1-2: build toc, write toc.yml
    try:
        toc_data = build_toc(notes_root)
    except TocError as e:
        raise UpdateError(str(e)) from e
    write_toc_yaml(toc_data, toc_out)

    # Step 3: validate course.yml against notes -- must abort before
    # touching course/ if anything is wrong
    try:
        config = CourseConfig.from_yaml(course_yaml)
    except FileNotFoundError:
        raise UpdateError(f"'{course_yaml}' not found.")
    except ValidationError as e:
        raise UpdateError(f"course.yml is invalid:\n{e}") from e

    results = run_course_checks(config, notes_root, toc_data)
    if any(results.values()):
        problems = [p for ps in results.values() for p in ps]
        raise UpdateError(
            "validation failed:\n" + "\n".join(f"  {p}" for p in problems)
        )

    # Step 4: unlock course/ (idempotent -- no-op if already writable)
    unlock_course(course_path)

    # Step 4b: copy course.yml into course/ so it's version-controlled there
    course_yml_src = Path(course_yaml).resolve()
    course_yml_dst = course_path / "course.yml"
    if course_yml_src != course_yml_dst.resolve():
        shutil.copy2(course_yml_src, course_yml_dst)

    # Step 5: copy + instrument
    # The manifest was already loaded by build_toc (step 1); we load it
    # again here rather than thread it through the call chain, since it's
    # a tiny file and the double read is cheaper than a refactor.
    try:
        manifest = NotesManifest.from_yaml(notes_root / "coursecraft.yml")
    except (FileNotFoundError, ValidationError) as e:
        raise UpdateError(f"could not load notes manifest: {e}") from e
    _copy_notes(notes_root, course_path, manifest)

    # Step 5b: strip chapters/appendices from base _quarto.yml so profiles
    # can set them per-date without duplicating what's already in the base.
    _strip_quarto_chapter_lists(course_path, title=config.course.title)

    # Step 6: generate homework / exam files
    generate_homework_files(config, course_path, manifest.conventions.macros_include)

    # Step 7: generate Quarto profile YAMLs (_quarto-<date>.yml)
    generate_profiles(config, toc_data, course_path)

    # Step 8: generate syllabus (course/index.qmd)
    generate_syllabus(config, toc_data, course_path)

    # Step 8b: write coursecraft-manifest.json for CI redirect anchoring
    _write_course_manifest(config, course_path)

    # Step 9: lock course/ (local safeguard against accidental hand-editing)
    if lock:
        lock_course(course_path)

    # Step 10: commit course/
    _commit_course(course_path)

    # Step 11: push course/ to remote (optional)
    if push:
        _git(["git", "-C", str(course_path), "push", "-u", "origin", "HEAD"], env=coursecraft_env())
