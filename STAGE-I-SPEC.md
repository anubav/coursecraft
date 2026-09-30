# Coursecraft Stage I — Project Specification

## Overview

Coursecraft is a Python CLI tool that generates section-specific Quarto course
websites from a shared master notes repository. The core problem it solves: a
single set of course notes (chapters, exercises, appendices) needs to be
delivered to students incrementally — only the material covered so far should
be visible on any given date — while the instructor maintains one canonical
source of content shared across multiple course sections and academic years.

**Current version:** 0.2.0
**Package:** `coursecraft` (installable via `pip install -e .`)
**Entry point:** `coursecraft` CLI

---

## The Three-Repository Architecture

A coursecraft deployment involves three Git repositories with distinct roles:

### 1. Notes repo (e.g. `anubav/logic-notes`)
The shared master content repository. Contains:
- `chapters/*.qmd` — lecture notes, one file per chapter
- `appendices/*.qmd` — supplementary material
- `exercises/*.qmd` — exercise fragments included by chapters
- `inserts/**/*.qmd` — reusable content fragments
- `assets/` — shared assets (macros, images, CSS)
- `_quarto.yml` — base Quarto configuration (theme, format settings)
- `coursecraft.yml` — the notes manifest (see below)

The notes repo is **read-only from coursecraft's perspective** during update.
Instructors edit it directly and push to a section-specific branch
(`section/<name>`) created by `coursecraft fetch-notes`.

### 2. Course repo (e.g. `anubav/logic-fall-2026`)
The per-section generated output repository. Contains only files produced by
`coursecraft update` — never hand-edited. Protected locally by read-only file
permissions (`chmod 0o444`) between update runs as a safeguard against
accidental edits. Served via GitHub Pages.

Key contents after update:
- Instrumented chapter/appendix `.qmd` files (sections wrapped in
  visibility-controlling divs)
- `_quarto-<date>.yml` — one Quarto profile per event date
- `index.qmd` — generated syllabus
- `hw-NN.qmd` / `exam-NN.qmd` — generated assignment files
- `hw-NN-solutions.qmd` — generated solutions files (when enabled)
- `_quarto.yml` — base config (stripped of chapter lists; title set to
  section-specific course title)
- `course.yml` — copy of the section's course config, version-controlled here
- `coursecraft-manifest.json` — maps lecture dates to section labels for CI
  redirect anchoring

### 3. Solutions repo (e.g. `anubav/logic-solutions`, private)
A private repository containing solution `.qmd` fragments. Cloned into
`course/solutions/` at render time by CI using an SSH deploy key. Never
committed to the course repo (`.gitignore`d). The instructor can also copy it
locally for preview rendering.

---

## Local Working Directory Structure

```
<section-dir>/          (e.g. fall-2026/)
  notes/                ← git clone of the notes repo (section branch)
  course/               ← git clone of the course repo
  course.yml            ← the section's course configuration file
  toc.yml               ← generated TOC (written by coursecraft update)
```

---

## Key Abstractions

### NotesManifest (`notes/coursecraft.yml`)

Describes the structural conventions of the notes repository so coursecraft
can interpret it without hardcoded assumptions. Parsed by `manifest.py` using
a Pydantic model with `extra="forbid"` (typos in field names fail immediately).

Key fields:
- `coursecraft_spec` — manifest format version (currently `"1.0"`)
- `requires` — minimum coursecraft version required (e.g. `">=0.2.0"`)
- `conventions.chapter_glob` — glob pattern for chapter files
- `conventions.appendix_dir_glob` — glob pattern for appendix files
- `conventions.exercise_glob` / `insert_glob` — fragment patterns
- `conventions.label_prefix` — prefix for section labels (e.g. `"sec-"`)
- `conventions.macros_include` — path to shared LaTeX macros include
- `conventions.raw_text_div_classes` — div classes whose content must not
  be reflowed (e.g. `lproof` for proof environments)

### CourseConfig (`course.yml`)

Describes a single section of a course: who, when, what. Parsed by `schema.py`
using Pydantic models with `extra="forbid"`. The authoritative source of truth
for everything section-specific.

Top-level structure:
```yaml
course:
  title: "Introduction to Logic"
  notes_repo: "git@github.com:anubav/logic-notes.git"
  solutions_repo: "git@github.com:anubav/logic-solutions.git"  # optional

section:
  instructor: "Anubav Vasudevan"
  instructor_email: "anubav@uchicago.edu"   # optional; used for mailto link
  course_number: "PHIL 20100"
  term: "Fall 2026"
  location: "Cobb 301"
  meeting_times: "MWF 10:30–11:20"
  start_date: "2026-09-28"
  end_date: "2026-12-11"
  description: "..."    # optional; appears at top of syllabus

lectures:
  - part: "Introduction"          # optional part grouping
    lectures:
      - date: "2026-09-28"
        sections: ["sec-ch1"]     # list of section labels covered
        cumulative: true          # default; false = windowed (show only this date's sections)
        name: "Overview"          # optional; overrides label-derived topic name

assignments:
  - name: "Homework 1"
    assigned: "2026-09-30"
    due: "2026-10-07"
    show_solutions: false
    exercises:
      - label: "sec-ch1-ex1"
        parts: [a, b, c]
```

### TOC (`toc.yml`)

An in-memory (and written-to-disk) representation of the notes repo's content
structure, built by scanning the notes directory. Maps section labels to titles,
paths, and nesting. Used by all downstream steps: profile generation, syllabus
generation, validation. Always rebuilt from source — never read from disk as
authoritative.

Structure:
```yaml
chapters:
  - path: "chapters/ch1.qmd"
    label: "sec-ch1"
    title: "Argument and Validity"
    sections:
      - label: "sec-ch1-intro"
        title: "Introduction"
      - label: "sec-ch1-proof"
        title: "Proof"
appendices:
  - ...
```

### Section Instrumentation

Chapter and appendix `.qmd` files are transformed ("instrumented") during the
notes→course copy. Every labeled `##` section heading is wrapped in a Quarto
conditional div:

```markdown
::: {.content-hidden unless-meta="sections.sec-ch1-intro"}
## Introduction {#sec-ch1-intro}
...section content...
:::
```

This allows a single instrumented file to show any subset of its sections
depending on the active Quarto profile's metadata. Instrumentation happens
once per update run; visibility is controlled entirely by profile metadata.

### Quarto Profiles (`_quarto-<date>.yml`)

One profile file per "event date" (lecture date, assignment assigned date,
assignment due date when `show_solutions=True`). Each profile specifies:

- `project.output-dir` — date-specific output directory (`_book/<date>`)
- `book.chapters` — only chapters with at least one visible section; homework
  files grouped under an "Assignments" part
- `book.appendices` — visible appendices
- `metadata.sections` — map of `label: true/false` controlling section
  visibility via the instrumented divs
- `format.html.include-in-header` — injected JavaScript variables:
  - `window.coursecraftSections` — the sections metadata (for live/dead
    schedule links in the syllabus)
  - `window.coursecraftHwFiles` — list of active hw/solutions `.html` files
    (for live/dead assignment links in the syllabus)

---

## CLI Commands

### `coursecraft init`
Initializes the course repo with placeholder files, a `.gitignore` (including
`solutions/`), and a pre-commit hook that prevents hand-editing of generated
files.

### `coursecraft fetch-notes <repo-url>`
Clones the notes repo into `./notes/` on a fresh `section/<dirname>` branch,
pushes the branch immediately to prevent name collisions, and installs
pre-commit hooks. Checks `requires:` in `coursecraft.yml` against the installed
coursecraft version before completing.

### `coursecraft update [--no-lock] [--push]`
The main pipeline. Runs all 11 steps (see below). `--no-lock` skips the
read-only chmod on `course/` (useful for local preview rendering).
`--push` pushes the course repo after committing.

### `coursecraft deploy [--force] [--solutions-repo <url>]`
One-time setup: writes the GitHub Actions CI workflow to the course repo,
optionally configures the SSH deploy key for the solutions repo, and pushes.
Subsequent updates use `coursecraft update --push`; `deploy` is not re-run.

---

## The Update Pipeline (11 steps)

1. **Build TOC** — scan `notes/` to build the TOC data structure
2. **Write `toc.yml`** — persist the TOC to disk for reference
3. **Validate** — parse and validate `course.yml`; run course checks (valid
   section labels, no dangling includes, etc.); abort before touching `course/`
   if anything fails
4. **Unlock `course/`** — `chmod 0o644` on all files (no-op on first run)
4b. **Copy `course.yml`** — copy the section's `course.yml` into `course/` for
    version control
5. **Copy + instrument** — copy `notes/` → `course/`, instrumenting
   chapter/appendix files in-flight; skip excluded dirs and generated files
5b. **Strip `_quarto.yml`** — remove chapters/appendices from the base
    `_quarto.yml` (profiles own the chapter list); set `book.title` to the
    section-specific course title; remove `author`
6. **Generate assignment files** — write `hw-NN.qmd`, `exam-NN.qmd`, and
   `*-solutions.qmd` files into `course/`
7. **Generate profiles** — write one `_quarto-<date>.yml` per event date
8. **Generate syllabus** — write `course/index.qmd` with info table, schedule
   (with live/dead section links), and assignments table (with live/dead
   hw/solutions links); includes JavaScript for link activation
8b. **Write `coursecraft-manifest.json`** — maps lecture dates to first section
    labels for CI redirect anchoring
9. **Lock `course/`** — `chmod 0o444` on all files (local safeguard)
10. **Commit** — stage all changes and commit with `coursecraft update` message
11. **Push** (optional) — push `course/` to its remote

---

## Key Design Decisions

### Notes/course separation
The notes repo contains instructor-authored content; the course repo contains
only generated output. This enables: (a) one notes repo serving multiple
sections on separate branches, (b) the course repo being fully regeneratable
from notes + `course.yml`, (c) read-only protection of generated files.

### Instrument-once, show/hide via profiles
Sections are wrapped in conditional divs once at copy time. Profile metadata
controls visibility at render time. This avoids generating separate `.qmd` files
per date and keeps the content single-sourced.

### Profile-per-event-date (not profile-per-lecture)
Profiles are generated at every date where the visible content set changes:
lecture dates, assignment assigned dates, and assignment due dates (when
solutions are shown). The CI workflow renders the profile matching today's date,
giving a rolling "up to here" view of the course.

### JavaScript scope constraint
JavaScript is used only for time-dependent course-layer UX (live/dead links in
the syllabus that depend on which profile is active). Static notes content never
uses JavaScript — this preserves portability and predictability of the notes
themselves.

### `requires:` version pinning
The notes manifest can declare a minimum coursecraft version
(`requires: ">=0.2.0"`). Checked in both `fetch-notes` (first contact with the
notes repo) and `update` (belt-and-suspenders). Raises a clear error with
upgrade instructions if the constraint isn't met.

### `extra="forbid"` on all Pydantic models
Typos in YAML field names (e.g. `show-solutions` instead of `show_solutions`)
fail immediately with a clear error rather than being silently ignored.

---

## Stage I Limitations (addressed in Stage II)

- **File-centric**: all functions take filesystem paths; no way to call core
  functions with in-memory objects directly
- **No web interface**: all operations are CLI-only
- **GitHub dependency**: rendering and delivery depend on GitHub Actions CI and
  GitHub Pages
- **Private solutions complexity**: SSH deploy key setup is manual and requires
  GitHub-specific configuration
- **Single-user**: no concept of user identity or access control
