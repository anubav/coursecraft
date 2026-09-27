"""
Checks that a real notes repo's file *content* satisfies what its
coursecraft.yml manifest declares. Deliberately separate from
manifest.py: that module validates the YAML's shape in isolation,
independent of any repo; these functions need an actual repo on disk
to scan.

Each check returns a list of human-readable problem strings; an empty
list means that check found nothing wrong.
"""

import re
from pathlib import Path
from typing import Union

from .manifest import NotesManifest
from .structure import LABEL_RE, HEADING_RE, FenceTracker, DIV_FENCE_RE
from .lint import find_unlabeled_sections

INCLUDE_RE = re.compile(r'\{\{<\s*include\s+([^\s>]+)\s*>\}\}')
EXERCISE_INCLUDE_RE = re.compile(
    r'\{\{<\s*include\s+/exercises/([^./\s>]+)\.qmd\s*>\}\}'
)

# globs whose matched files are worth scanning for labels/includes --
# everything a manifest declares, in the order it's most useful to report
_ALL_CONTENT_GLOBS = [
    "chapter_glob",
    "appendix_dir_glob",
    "exercise_glob",
    "insert_glob",
]


def _matched_files(manifest: NotesManifest, repo_root: Path, glob_fields=None):
    """Yield (relative_path, absolute_path) for every file matched by
    the given glob fields (default: all of them), de-duplicated in
    case two globs happen to overlap."""
    conv = manifest.conventions
    seen = set()
    for field in glob_fields or _ALL_CONTENT_GLOBS:
        pattern = getattr(conv, field)
        for f in sorted(repo_root.glob(pattern)):
            if f in seen or not f.is_file():
                continue
            seen.add(f)
            yield f.relative_to(repo_root), f


def check_globs_against_repo(manifest: NotesManifest, repo_root: Union[str, Path]) -> list[str]:
    """A glob matching zero files usually means a typo'd directory
    name -- this is schema-adjacent but needs the filesystem, so it
    can't live in manifest.py itself."""
    repo_root = Path(repo_root)
    conv = manifest.conventions
    problems = []

    for field_name in _ALL_CONTENT_GLOBS:
        pattern = getattr(conv, field_name)
        if not list(repo_root.glob(pattern)):
            problems.append(
                f"{field_name} ({pattern!r}) matches no files under {repo_root}"
            )

    if conv.macros_include:
        macro_path = repo_root / conv.macros_include.lstrip("/")
        if not macro_path.exists():
            problems.append(
                f"macros_include ({conv.macros_include!r}) does not "
                f"exist at {macro_path}"
            )

    return problems


def check_missing_labels(manifest: NotesManifest, repo_root: Union[str, Path]) -> list[str]:
    """Same check as `coursecraft lint`, run across every chapter and
    appendix file. Exercises/inserts are deliberately excluded here --
    they aren't sections and have no sec- label requirement."""
    repo_root = Path(repo_root)
    problems = []
    for rel, f in _matched_files(manifest, repo_root, ["chapter_glob", "appendix_dir_glob"]):
        text = f.read_text(encoding="utf-8")
        for v in find_unlabeled_sections(text):
            problems.append(f"{rel}:{v.line_number}: \"## {v.heading_text}\" has no label")
    return problems


def check_duplicate_labels(manifest: NotesManifest, repo_root: Union[str, Path]) -> list[str]:
    """Every {#label} in the repo -- sections, definitions, exercises,
    theorems, anything -- must be unique. A duplicate is invisible
    until a render either resolves crossrefs ambiguously or fails
    outright; it's cheap to catch here instead."""
    repo_root = Path(repo_root)
    locations: dict[str, list[str]] = {}
    for rel, f in _matched_files(manifest, repo_root):
        text = f.read_text(encoding="utf-8")
        for i, line in enumerate(text.split("\n"), start=1):
            for m in LABEL_RE.finditer(line):
                locations.setdefault(m.group(1), []).append(f"{rel}:{i}")

    problems = []
    for label in sorted(locations):
        where = locations[label]
        if len(where) > 1:
            problems.append(f"label '{label}' declared more than once: " + ", ".join(where))
    return problems


def check_dangling_includes(manifest: NotesManifest, repo_root: Union[str, Path]) -> list[str]:
    """Every absolute {{< include /... >}} must resolve to a real
    file. A dangling include otherwise only fails at render time, with
    an error that doesn't point back at the actual typo."""
    repo_root = Path(repo_root)
    problems = []
    for rel, f in _matched_files(manifest, repo_root):
        text = f.read_text(encoding="utf-8")
        for m in INCLUDE_RE.finditer(text):
            target = m.group(1)
            if not target.startswith("/"):
                continue  # relative includes resolve differently; not this check's job
            target_path = repo_root / target.lstrip("/")
            if not target_path.exists():
                problems.append(
                    f"{rel}: {{{{< include {target} >}}}} does not "
                    f"resolve (expected {target_path})"
                )
    return problems


def check_chapter_headings(manifest: NotesManifest, repo_root: Union[str, Path]) -> list[str]:
    """Each chapter/appendix file should have exactly one top-level
    '#' heading, carrying a label -- catches a leftover second '#'
    heading (e.g. from a bad merge) or a chapter that never got its
    own label. chapter_marker_class is only enforced for chapter_glob
    matches: the manifest has no separate field for an appendix's own
    marker class, so this check doesn't invent a requirement it can't
    actually verify for appendices."""
    repo_root = Path(repo_root)
    conv = manifest.conventions
    problems = []

    for glob_field in ["chapter_glob", "appendix_dir_glob"]:
        for rel, f in _matched_files(manifest, repo_root, [glob_field]):
            text = f.read_text(encoding="utf-8")
            tracker = FenceTracker()
            top_headings = []
            for line in text.split("\n"):
                is_fence = tracker.consume(line)
                if not is_fence and tracker.at_structural_top_level():
                    m = HEADING_RE.match(line)
                    if m and len(m.group(1)) == 1:
                        top_headings.append(line)

            if len(top_headings) == 0:
                problems.append(f"{rel}: no top-level '#' chapter heading found")
                continue
            if len(top_headings) > 1:
                problems.append(
                    f"{rel}: {len(top_headings)} top-level '#' headings "
                    f"found (expected exactly 1)"
                )
                continue

            heading = top_headings[0]
            if not LABEL_RE.search(heading):
                problems.append(
                    f"{rel}: chapter heading has no "
                    f"{{#{conv.label_prefix}...}} label"
                )
            elif glob_field == "chapter_glob" and conv.chapter_marker_class:
                if f".{conv.chapter_marker_class}" not in heading:
                    problems.append(
                        f"{rel}: chapter heading missing "
                        f".{conv.chapter_marker_class} class"
                    )

    return problems


def check_exercise_labels(manifest: NotesManifest, repo_root: Union[str, Path]) -> list[str]:
    """Every {{< include /exercises/<name>.qmd >}} in a chapter or appendix
    must be the direct body of a :::{#exr-<name>} div. This is what makes
    @exr-<name> cross-references auto-number correctly in homework files."""
    repo_root = Path(repo_root)
    problems = []

    for rel, f in _matched_files(manifest, repo_root, ["chapter_glob", "appendix_dir_glob"]):
        text = f.read_text(encoding="utf-8")
        tracker = FenceTracker()
        exr_stack: list[str | None] = []

        for line in text.split("\n"):
            is_fence = tracker.consume(line)
            if is_fence:
                m = DIV_FENCE_RE.match(line)
                if m:
                    rest = m.group(3).strip()
                    if rest:
                        exr_m = re.search(r'#exr-([\w-]+)', rest)
                        exr_stack.append(exr_m.group(1) if exr_m else None)
                    elif exr_stack:
                        exr_stack.pop()
            elif not tracker.in_protected_block():
                inc_m = EXERCISE_INCLUDE_RE.search(line)
                if inc_m:
                    name = inc_m.group(1)
                    current_exr = next(
                        (label for label in reversed(exr_stack) if label is not None),
                        None,
                    )
                    if current_exr != name:
                        include_str = "{{< include /exercises/" + name + ".qmd >}}"
                        exr_str = ":::{#exr-" + name + "}"
                        problems.append(
                            f"{rel}: {include_str} is not inside a '{exr_str}' div"
                        )
    return problems


#: every check, run together by `coursecraft validate-notes`
ALL_CHECKS = [
    check_globs_against_repo,
    check_chapter_headings,
    check_missing_labels,
    check_duplicate_labels,
    check_dangling_includes,
    check_exercise_labels,
]


def run_all_checks(manifest: NotesManifest, repo_root: Union[str, Path]) -> dict[str, list[str]]:
    """Run every check, keyed by check name, including checks that
    found nothing (empty list) so a caller can report a clean summary."""
    return {check.__name__: check(manifest, repo_root) for check in ALL_CHECKS}
