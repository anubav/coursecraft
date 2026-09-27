"""
coursecraft toc.

Builds a table of contents for the notes repo currently checked out at
./notes: every chapter and appendix, in the order declared by
notes/_quarto.yml (not lexical filename order, which would impose a
naming convention on the notes repo's author -- _quarto.yml's own
`book: chapters:`/`appendices:` list is the order Quarto itself
already uses for `quarto preview`, so this reuses a signal the notes
repo's author already has to get right, rather than asking for a
second one). Each chapter/appendix lists its own labeled '##'
sections, in document order -- the same underlying scan instrument.py
uses to decide what to wrap, and what `update`'s validation checks
(A/B/C/D) use against course.yml.

Written to ./toc.yml, sibling to course.yml -- never inside notes/
itself, since notes/ is a git clone that gets pushed back to the
master repo via sync-back, and a stray generated file there could get
committed and pushed upstream by accident. Always overwrites: this is
100% derived data, nothing to protect, unlike course.yml.

Only a flat `book: chapters:`/`appendices:` list is supported for now
-- see ARCHITECTURE.md if a notes repo's _quarto.yml uses `part:`
groupings instead.
"""

from pathlib import Path
from typing import Union

import yaml

from .manifest import NotesManifest
from .structure import find_headings, ATTR_BLOCK_RE


class TocError(Exception):
    pass


def _clean_title(heading_text: str) -> str:
    """Strip a trailing {...} attribute block for display purposes --
    find_headings() deliberately leaves this in the raw heading_text,
    since stripping it isn't every caller's job."""
    return ATTR_BLOCK_RE.sub('', heading_text).strip()


def _load_quarto_order(notes_root: Path) -> tuple[list[str], list[str]]:
    quarto_yml = notes_root / "_quarto.yml"
    if not quarto_yml.exists():
        raise TocError(f"'{quarto_yml}' not found.")
    data = yaml.safe_load(quarto_yml.read_text(encoding="utf-8")) or {}
    book = data.get("book", {}) or {}
    chapters = book.get("chapters", []) or []
    appendices = book.get("appendices", []) or []
    for entry in chapters + appendices:
        if not isinstance(entry, str):
            raise TocError(
                "_quarto.yml uses part: groupings, which aren't supported yet."
            )
    return chapters, appendices


def _build_entry(path: Path, notes_root: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    all_headings = find_headings(text)

    h1 = next((h for h in all_headings if h.level == 1), None)
    title = _clean_title(h1.heading_text) if h1 else path.stem
    label = h1.label if h1 else None

    sections = [
        {"label": h.label, "title": _clean_title(h.heading_text)}
        for h in all_headings
        if h.level == 2 and h.label is not None
    ]

    return {
        "path": str(path.relative_to(notes_root)),
        "label": label,
        "title": title,
        "sections": sections,
    }


def build_toc(notes_root: Union[str, Path]) -> dict:
    """Returns {"chapters": [...], "appendices": [...]}, each entry
    with path/label/title/sections, in notes/_quarto.yml's own order.
    An entry in _quarto.yml that doesn't match the manifest's
    chapter_glob/appendix_dir_glob (e.g. a front-matter index.qmd) is
    silently excluded -- it's not a real content chapter."""
    notes_root = Path(notes_root)
    manifest_path = notes_root / "coursecraft.yml"
    if not manifest_path.exists():
        raise TocError(f"'{manifest_path}' not found.")
    manifest = NotesManifest.from_yaml(manifest_path)
    conv = manifest.conventions

    chapter_order, appendix_order = _load_quarto_order(notes_root)

    chapter_matches = set(notes_root.glob(conv.chapter_glob))
    appendix_matches = set(notes_root.glob(conv.appendix_dir_glob))

    chapters = [
        _build_entry(notes_root / rel, notes_root)
        for rel in chapter_order
        if (notes_root / rel) in chapter_matches
    ]
    appendices = [
        _build_entry(notes_root / rel, notes_root)
        for rel in appendix_order
        if (notes_root / rel) in appendix_matches
    ]

    return {"chapters": chapters, "appendices": appendices}


def write_toc_yaml(toc_data: dict, path: Union[str, Path] = "toc.yml") -> None:
    Path(path).write_text(yaml.dump(toc_data, sort_keys=False), encoding="utf-8")
