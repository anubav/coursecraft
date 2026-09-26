# coursecraft: architecture and design rationale

This document exists because the *reasoning* behind several decisions
here isn't recoverable from the code alone. Where something non-obvious
is done a particular way, this file says why -- so a future change can
be made deliberately, with the original trade-off in view, rather than
by re-deriving (or accidentally re-breaking) it from scratch.

## The big picture

Three kinds of repo, with a clean separation of concerns:

- **`logic-notes`** (and any similarly-structured course-notes repo) --
  the portable, public master content. Chapters, appendices, exercises,
  inserts. No profile logic, no per-section anything. Just the notes.
- **`logic-solutions`** -- private. Raw solution fragments plus
  aggregator pages. Cloned into a section repo's `solutions/` (gitignored)
  only when needed.
- **`coursecraft`** (this repo) -- the tool. Portable across any master
  repo that declares a `coursecraft.yml` manifest. Reads a section's
  `course.yaml` and generates everything section-specific: formatted
  content, Quarto profiles, homework/exam pages, a syllabus, and
  (eventually) a scheduled, date-gated deployment.

A **section repo** (not yet built) is what actually gets deployed for
one instance of a course: a clone of the master notes repo, a
`course.yaml`, and whatever `coursecraft` generates from the two.

## Why the master repo holds no profile logic

Early on, `content-hidden`/`when-profile` divs were hand-authored
directly in the notes, nested one level per lecture boundary. This
became unmaintainable: adding lecture N+1 meant re-editing every
already-written div in every earlier chapter. The fix was to separate
*structure* (what sections exist, permanent) from *reveal schedule*
(which sections are visible when, changes every term) into two
different artifacts entirely -- the master repo only ever holds the
former.

## Coarse-grained master content, not one file per section

Each chapter/appendix is **one file**, not one file per subsection.
This was a deliberate trade-off: Quarto resolves cross-references and
citations correctly during `quarto preview` only when the referencing
and referenced content are both already loaded -- which requires
either a full book render or, much more conveniently, both living in
the same file. Splitting a chapter into many small files would break
this for ordinary hand-editing.

The granularity this creates: a reveal/hide decision can only happen at
a `##` heading boundary (a whole labeled section), never mid-file. A
lecture's `notes_end` therefore always names a `{#sec-...}` label, never
an arbitrary point in the text.

## Label convention: `sec-<chapter-slug>-<heading-slug>`

Chapter/appendix subsections often share generic titles (`## Introduction`
appears in nearly every chapter). A flat, unprefixed slug scheme would
collide constantly. Every generated label is chapter-scoped; only the
chapter/appendix's own top-level label is the bare `sec-<slug>` form.

Labels are **linted, not auto-generated** (`coursecraft lint`). A
section label is a persistent identifier other content may eventually
cross-reference -- naming it is a decision for whoever writes the
heading, not something safe to script silently. Formatting
(`coursecraft reflow`) has no such ambiguity (there's one correct way
to wrap a sentence), which is why it *is* automated.

## Semantic linebreaks, not column-wrapping

Every `.qmd` file is formatted one sentence per line, not wrapped to a
fixed column. This was chosen specifically for git-diff cleanliness:
editing one sentence changes exactly one line; under column-wrapping,
the same edit reflows every subsequent line in the paragraph. Verified
directly (not just argued): an identical one-sentence insertion produced
a 3-line diff under semantic linebreaks versus a 52-line diff under
column-wrap, for the same edit.

Trade-off accepted: line-by-line references ("see line 12") aren't
stable across two people's differently-sized editors, since on-screen
wrapping is now purely a *display* concern (`editor.wordWrap`), not
tied to the file's actual line breaks.

### What reflow must never touch, and why

Each of these was found by a real bug, not anticipated in advance:

- **`.lproof` divs** -- the extension's own parser reads this content
  as raw text; exact indentation and per-line numbering are load-bearing.
  Protected as a whole block, inherited into anything nested inside,
  regardless of what individual lines look like (an early version only
  protected lines matching a numbered-list pattern, which worked by
  coincidence until a non-numbered continuation line proved it wasn't
  a real guarantee).
- **Bare thematic breaks** (`---`, `***`, `___`) -- merging one into a
  paragraph makes Pandoc's smart-typography extension silently convert
  it into a literal em dash instead of a horizontal rule.
- **4-space-indented continuation lines** -- Pandoc requires this exact
  indentation to keep a paragraph attached to a footnote or list item;
  stripping it (ordinary reflow's default behavior) silently detaches
  the paragraph into ordinary inline text.
- **A wrapped line starting with something that looks like a list
  marker** (a bare year like `1975.`, a Pandoc example-list ref like
  `@fig-x)`, or a parenthesized letter marker like `(a).`) -- confirmed
  by direct reproduction to make Pandoc start a brand-new nested list
  mid-sentence. The fix glues the offending token onto the end of the
  previous line rather than ever allowing it to start one.

## `course.yaml`: schema as a public API

The Pydantic model (`coursecraft.schema.CourseConfig`) is the single,
authoritative definition of a valid section config. This choice was
made partly in anticipation of a future web UI: as long as the web
backend imports the *same* `CourseConfig` (rather than reimplementing
validation), a form submission that validates is guaranteed to be
accepted by `coursecraft` too -- no second copy of "what makes a
lecture entry valid" to drift out of sync. Pydantic's free
`model_json_schema()` export also means a JSON-Schema-driven form
library (or a Django `django-jsonform` widget) can generate a working
form directly from this model, with no separate schema to maintain.

YAML on disk remains the durable, git-trackable source of truth even
once a web UI exists -- the UI edits/generates the file; it does not
replace it with an in-memory or database-only representation.

Multiple `model_validator(mode="after")` methods on the same model run
**sequentially**, and the first to raise stops the rest from running in
that pass (unlike field-level errors, which are collected together).
A badly broken file may need a couple of fix-and-rerun cycles before
`coursecraft validate` reports a clean bill of health -- confirmed
directly, not assumed.

## `coursecraft.yml`: the same treatment, for the same reason

The notes-repo manifest gets its own Pydantic model (`NotesManifest`,
in `manifest.py`, kept separate from `schema.py` since the two describe
different things -- `course.yaml` is one section's schedule, unique
per term; `coursecraft.yml` is the shape of the master content itself,
the same for every section built from a given notes repo). Same
motivation as `course.yaml`: without this, a typo'd field name (e.g.
`exercize_glob`) would silently be ignored by a plain dict-based
parser, only surfacing later as a confusing failure deep inside
label-scanning or instrumentation code.

`model_config = {"extra": "forbid"}` is what actually catches the typo
case -- without it, an unrecognized field is just silently dropped.
`coursecraft_spec` is checked against a set of versions this build of
coursecraft understands, so a manifest written for a newer spec fails
with an "upgrade coursecraft" message rather than a mysterious downstream
error.

Whether the declared globs actually match real files is a *separate*
concern from schema validity, and deliberately lives as a plain
function (`check_globs_against_repo`) rather than inside the Pydantic
model: the model can only validate the shape of the YAML in isolation,
while this check needs an actual repo on disk to compare against.
`coursecraft validate-notes <repo-root>` runs both together.

`repo_checks.py` extends this same idea to the repo's actual file
*content*, not just its directory shape: missing `##` labels (the same
check `coursecraft lint` runs, bundled in here too), a top-level `#`
chapter heading that's missing, duplicated, or missing its marker
class, a dangling `{{< include /... >}}` that doesn't resolve to a
real file, and -- found real instances of on the first run against
`logic-notes` itself, not merely anticipated -- **duplicate `{#label}`
declarations** anywhere in the repo. Two theorems in `logic-notes` had
been copy-pasted with the same label never renamed (one pair even had
mismatched content: a completeness theorem left labeled
`thm-soundness-s`), invisible until either a render broke or a
crossref silently pointed at the wrong one. `coursecraft validate-notes`
now catches this class of mistake before either happens.

## Lecture reveal: cumulative by default, windowed by explicit choice

`notes_start` left blank means "continue from the frontier" (the
furthest `notes_end` reached by any earlier lecture) and defaults to
**cumulative** reveal -- once introduced, a section stays visible
going forward, so students can always review earlier material.

An **explicit** `notes_start` signals a deliberately scoped view (e.g.
a review lecture revisiting material out of order) and defaults to
**windowed** reveal instead -- only that lecture's own range is shown,
so it doesn't have to also imply "reveal everything up to here."
`cumulative: true`/`false` on a lecture always overrides the default
either way.

The frontier only ever **advances**, never retreats -- a windowed
review lecture doesn't reset what later lectures continue from.

## Homework/solutions: two files, not a metadata flag

Each assignment generates `hw-NN.qmd` (prompts) and, once `due` arrives
*and* `show_solutions` is true, a **separate** `hw-NN-solutions.qmd`
(prompts and solutions together, self-contained) that replaces it in
that profile's chapter list.

This was chosen over a `content-hidden unless-meta="solutions.*"` div
inside one file because it reuses the *same* primitive already used for
lecture reveal -- which file is in a profile's chapter list -- rather
than introducing a second gating mechanism. `hw-NN-solutions.qmd` must
be fully self-contained (re-transcluding each exercise prompt, not just
its solution) because the profile that includes it never includes
`hw-NN.qmd` at all, so a crossref back to it would have no target.

Solutions never un-reveal once shown -- no `solutions_end` exists in
the schema. `due` is kept as its own distinct field (rather than being
folded into `show_solutions` timing) specifically so that a later,
unrelated feature -- disabling online submission at the due date, once
the site gains that interactivity -- has a date to attach to without
needing to un-conflate anything retroactively.

## Profile-break rule

A new Quarto profile is needed at every date where the *visible content
set* changes at all: every lecture date, every assignment's `assigned`
date, and every assignment's `due` date **only if** `show_solutions` is
true for that assignment (otherwise `due` triggers nothing -- the
homework page just stays as-is). This is computed as one sorted
timeline across all lectures and assignments together, not lecture
dates with homework patched in separately.

## Deployment must be date-gated, not just redirect-gated

A scheduler page that redirects to "today's" profile is a **UX
convenience only**, not an access control. If every profile's build
output exists on the server simultaneously, nothing stops a student
from typing next week's URL directly. The actual fix belongs in the
*publish* step: each rebuild only publishes the set of profiles whose
activation date has already passed as of that run. A future profile
doesn't exist on the server yet -- there's no URL to guess, because
there's nothing there to serve. Nothing already published is ever
taken down, so existing bookmarks keep working.

This is a deploy-phase mechanism, not yet implemented, noted here so
the eventual GitHub Actions workflow is built with it in mind from the
start rather than retrofitted after a real access-control question.

## Explicitly deferred, and why that's a safe deferral

- **Student roster / access control.** A genuinely different problem
  from date-gating (stops an unenrolled outsider seeing anything, not
  an enrolled student seeing something too early) -- deferred until
  the web interface exists to manage it, since access control without
  a UI to administer it is unlikely to be usable anyway.
- **Onboarding helpers for pre-existing, non-coursecraft-native content**
  (`merge_chapter`, `strip_profile_wrapping` -- used once, to convert
  last year's ad hoc notes). Deliberately not carried into this package:
  the specific legacy convention they handled (hand-rolled
  `content-hidden`/`when-profile` wrapping) is unlikely to recur for a
  different instructor's pre-existing notes. Not lost -- sitting in
  `logic-notes`'s git history if a genuine second case ever shows up --
  just not maintained, tested surface area until then.
- **Interactive homework submission.** Long-term goal (students
  answering online, a due date disabling that rather than just
  triggering solutions), requiring a real backend (e.g. Django)
  injecting into the Quarto output. Not designed yet, but the schema's
  `due` field is already positioned to support it without rework.
- **Label-ordering sanity check.** `update`'s human-error checks (do
  `course.yaml`'s referenced labels/exercises still exist in `notes/`)
  only catch a label that's missing, not one that exists but is out of
  order -- e.g. a `notes_end` typo pointing at content earlier in the
  book than an already-covered lecture. Deferred because it needs real
  machinery (each label's absolute document position, not just
  existence), not because it's low-value.
- **`coursecraft sync-back`**, automating branch -> commit -> push ->
  open-PR for returning an edited `notes/` to the master repo at
  term's end. Plain git already does this (practiced by hand earlier
  in this project); only worth automating if that manual sequence
  becomes real, repeated friction.

## `fetch-notes`: section branches, not main, and why they're pushed immediately

Now that `logic-notes`'s `main` requires a pull request to merge into
(a deliberate choice, made once the repo was mature enough that
occasional pushes justified the friction), a section's working copy of
the notes can't just sit on `main` while it's edited during the term --
`coursecraft fetch-notes` checks it out onto a fresh `section/<name>`
branch instead (named after the section's own directory by default),
leaving day-to-day commits and pushes to that branch unrestricted, and
reserving the PR requirement for the one moment those changes actually
rejoin the shared repo at term's end.

The branch is **pushed immediately** on creation, empty of any
section-specific commits yet. This closes a real race condition, not
a hypothetical one: two sections created around the same time could
otherwise pick the same directory/branch name and only discover the
collision much later, whichever one happens to push second. Both
`fetch-notes` guardrails (refusing an already-existing `notes/`
directory, refusing an already-taken branch name) mirror `init`'s own
"error if this already happened" philosophy, verified directly against
the real `logic-notes` remote rather than just asserted.

`fetch-notes` takes no repo URL as an argument -- it reads
`course.notes_repo` (and optional `course.notes_branch`) from
`course.yaml` in the current directory, and refuses to run at all if
that file doesn't exist (a short, direct error -- this is a common
enough mistake that a terse message is more useful than an explanation
every time). This was originally just "where does the URL come from,"
but turned out to double as a safeguard against a real mistake: running `fetch-notes` again from *inside* an already-cloned
`notes/` directory (which structurally can never have its own
`course.yaml`, since that file lives one level up, in the section
folder) now fails immediately and clearly instead of silently cloning
a nested `notes/notes/`. Confirmed by reproducing the exact failure
against the real repo before and after the fix.

`fetch-notes` validates only the `course:` block of `course.yaml`
(`CourseConfig.load_course_info`), not the whole file. This matters
because `fetch-notes` runs *before* the intended course.yaml-filling
wizard, right after `init` has scaffolded every other required field
as a literal `REPLACE_ME` -- a full `CourseConfig.from_yaml` validation
at this point would always fail on the placeholder dates, blocking
exactly the workflow `init` -> `fetch-notes` -> wizard -> `update` was
designed to support. Confirmed as a real bug, not a hypothetical: the
original implementation genuinely failed against a freshly-`init`'d
`course.yaml` before this fix, and genuinely succeeds after it. Full
validation of the whole file (`coursecraft validate`) remains exactly
as strict as before -- only `fetch-notes`'s own narrower need changed.

`notes_branch` (optional, defaults to the repo's own default branch)
exists because an instructor may want to build a section off their
own long-lived custom branch of the notes repo, without ever intending
to merge it into `main` -- confirmed that cloning a specific branch
still fetches every other branch too (not just the one checked out),
so nothing about future sync-back work is foreclosed by this choice.

## `init`: why it's separate from `fetch-notes`, and what it protects

`init` and `fetch-notes` are deliberately separate commands, not
folded together, because they have fundamentally different failure
profiles: `init` is 100% local (filesystem + git, essentially can't
fail for reasons outside your control), while `fetch-notes` depends on
the network and produces a real external side effect (a pushed
branch). Merging them would mean a failed clone leaves an ambiguous
half-done command -- ordering also matters for a different reason:
`fetch-notes` now requires `course.yaml` to already exist, so `init`
has to run first regardless. `build` composes both (plus the future
`course.yaml`-filling wizard, `update`, and `deploy`) for the "just do
everything" experience neither individual command should try to be.

`init` creates two independent things, with deliberately different
"already exists" behavior:

- **`./course/`** -- a fresh git repo, checked *first*. Already
  existing is a hard error, same "error if already done" philosophy
  as `fetch-notes`'s own guards. Checking this before touching
  `course.yaml` at all means a failed `init` never leaves a stray
  scaffolded file behind as a side effect.
- **`./course.yaml`** -- if missing, scaffolded with a real
  `notes_repo` (required as a CLI argument, not a placeholder --
  unlike every other required field, `notes_repo` has no format
  validation in the schema, so a placeholder here would silently pass
  `coursecraft validate` and only fail much later, deep inside
  `fetch_notes`'s own `git clone`, as a confusing error pointing at an
  obviously-fake URL). Every other required field is set to the
  literal string `REPLACE_ME` -- deliberately, for the date fields
  especially, since that fails `coursecraft validate` loudly (bad date
  format) rather than a fake-but-parseable date sailing through
  unnoticed. If `course.yaml` already exists, it's left completely
  untouched -- never overwritten, even partially, even if fields
  passed as CLI arguments (like `notes_branch`) differ from what's
  already there.

**`course/` is protected by two layers, split across `init` and
`update` for a reason.** Filesystem read-only permissions (chmod'ing
everything after each regeneration) belong to `update`, since there's
nothing to protect before the first `update` ever runs -- `init`
doing a chmod pass on an empty folder would be pointless, and `update`
would just have to undo it immediately anyway to do its own work. But
a **git pre-commit hook** rejecting any commit into `course/` unless
`coursecraft` itself set `COURSECRAFT_INTERNAL=1` first belongs in
`init`, installed from the very first commit onward -- deferring it to
`update`'s first run would leave a real gap where a stray manual
commit right after `init` wouldn't be caught by anything. Confirmed
with a real (non-mocked) commit attempt in both directions, not just
asserted: a manual `git commit` without the env var is rejected by the
actual hook; the same commit succeeds with it set.

`coursecraft`'s own internal commits (in `init`, and later `update`)
set their own `GIT_AUTHOR_NAME`/`EMAIL` and `GIT_COMMITTER_NAME`/`EMAIL`
explicitly, rather than relying on the host machine having a git
identity configured at all -- found this the hard way, when the test
suite's own sandbox (and, by the same logic, a fresh CI runner) had no
global git identity set up, which would otherwise make every
automated commit fail outright. Giving these commits a consistent,
distinct identity (`coursecraft <coursecraft@localhost>`) is also just
correct on its own terms: a 100%-generated commit shouldn't be
attributed to whichever human happened to be running the command.

## Package structure

```
src/coursecraft/
├── structure.py   # fence tracking, heading/label detection, list-marker
                    # recognition -- generic parsing, no formatting or
                    # validation decisions
├── reflow.py       # the formatting engine, built on structure.py
├── lint.py         # missing-label detection (report only)
├── schema.py       # course.yaml: Pydantic models + validation
├── manifest.py     # coursecraft.yml: Pydantic model + validation
├── repo_checks.py  # checks a real notes repo's content against its manifest
├── fetch.py        # fetch-notes: clone onto a section/<name> branch
├── init.py         # init: scaffold course/ + a placeholder course.yaml
└── cli.py          # thin argparse wrapper: reflow / lint / validate /
                      # validate-notes / fetch-notes / init
```

`cli.py` is intentionally thin -- every real function is directly
importable (`from coursecraft.schema import CourseConfig`,
`from coursecraft import reflow`), so a future web backend or test
suite calls the same code the CLI does, never a CLI subprocess wrapper
around logic that only exists inside `if __name__ == "__main__"`.

## Testing philosophy

Every non-trivial behavior in this document was originally verified by
building a small reproduction and inspecting real output -- rendering
through Quarto, diffing HTML text, checking exit codes -- rather than
by reasoning alone. `tests/` converts the ones worth protecting against
regression into real, repeatable `pytest` cases. Where a bug was found
and fixed (the thematic-break/em-dash conversion, the dangerous
line-start collision, the footnote-continuation-indentation strip), the
corresponding test is a **regression test** for that exact bug, not a
generic "does it work" check -- the goal is that if any of these ever
break again, `pytest` catches it before a render does.
