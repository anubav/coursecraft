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
  `course.yml` and generates everything section-specific: formatted
  content, Quarto profiles, homework/exam pages, a syllabus, and
  (eventually) a scheduled, date-gated deployment.

A **section repo** (not yet built) is what actually gets deployed for
one instance of a course: a clone of the master notes repo, a
`course.yml`, and whatever `coursecraft` generates from the two.

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
a `##` heading boundary (a whole labeled section), never mid-file. Each
label in a lecture's `sections` list therefore always names a
`{#sec-...}` label, never an arbitrary point in the text.

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

## `course.yml`: schema as a public API

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
different things -- `course.yml` is one section's schedule, unique
per term; `coursecraft.yml` is the shape of the master content itself,
the same for every section built from a given notes repo). Same
motivation as `course.yml`: without this, a typo'd field name (e.g.
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

Each lecture carries `sections: list[str]` -- an explicit list of
section labels to show -- and `cumulative: bool = True`.

`cumulative: true` (the default) adds those labels to the running
**frontier**: the ever-growing set of sections visible to students.
Once a section enters the frontier it stays visible in every subsequent
profile, so students can always review earlier material.

`cumulative: false` signals a deliberately scoped view (e.g. a review
lecture revisiting material out of order): **only** the labels in
`sections` are shown for that profile, ignoring the frontier entirely.

The frontier only ever **advances**, never retreats -- a
`cumulative: false` review lecture doesn't reset what later lectures
continue from.

A chapter-level label in `sections` (the bare `sec-<slug>` form) is
automatically expanded to include all of that chapter's subsection
labels by `_expand_labels` in `profiles.py`, so a lecture that covers
an entire chapter needs only the one top-level label.

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
- **Label-ordering sanity check.** ~~Deferred.~~ ~~Now implemented as
  check D in `course_checks.py`.~~ **Removed.** The sections-based
  schema makes a sequential ordering check meaningless: `sections` is
  an explicit list, not an interval, so there is no inherent ordering
  to enforce. Check A (label existence) still validates that every
  label in `lec.sections` actually exists in the notes, using
  `label_positions()` from `toc.py`.
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
`course.yml` in the current directory, and refuses to run at all if
that file doesn't exist (a short, direct error -- this is a common
enough mistake that a terse message is more useful than an explanation
every time). This was originally just "where does the URL come from,"
but turned out to double as a safeguard against a real mistake: running `fetch-notes` again from *inside* an already-cloned
`notes/` directory (which structurally can never have its own
`course.yml`, since that file lives one level up, in the section
folder) now fails immediately and clearly instead of silently cloning
a nested `notes/notes/`. Confirmed by reproducing the exact failure
against the real repo before and after the fix.

`fetch-notes` validates only the `course:` block of `course.yml`
(`CourseConfig.load_course_info`), not the whole file. This matters
because `fetch-notes` runs *before* the intended course.yml-filling
wizard, right after `init` has scaffolded every other required field
as a literal `REPLACE_ME` -- a full `CourseConfig.from_yaml` validation
at this point would always fail on the placeholder dates, blocking
exactly the workflow `init` -> `fetch-notes` -> wizard -> `update` was
designed to support. Confirmed as a real bug, not a hypothetical: the
original implementation genuinely failed against a freshly-`init`'d
`course.yml` before this fix, and genuinely succeeds after it. Full
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
`fetch-notes` now requires `course.yml` to already exist, so `init`
has to run first regardless. `build` composes both (plus the future
`course.yml`-filling wizard, `update`, and `deploy`) for the "just do
everything" experience neither individual command should try to be.

`init` creates two independent things, with deliberately different
"already exists" behavior:

- **`./course/`** -- a fresh git repo, checked *first*. Already
  existing is a hard error, same "error if already done" philosophy
  as `fetch-notes`'s own guards. Checking this before touching
  `course.yml` at all means a failed `init` never leaves a stray
  scaffolded file behind as a side effect.
- **`./course.yml`** -- if missing, scaffolded with a real
  `notes_repo` (required as a CLI argument, not a placeholder --
  unlike every other required field, `notes_repo` has no format
  validation in the schema, so a placeholder here would silently pass
  `coursecraft validate` and only fail much later, deep inside
  `fetch_notes`'s own `git clone`, as a confusing error pointing at an
  obviously-fake URL). Every other required field is set to the
  literal string `REPLACE_ME` -- deliberately, for the date fields
  especially, since that fails `coursecraft validate` loudly (bad date
  format) rather than a fake-but-parseable date sailing through
  unnoticed. If `course.yml` already exists, it's left completely
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

## `_gitutil.py`: extracted before it would have tripled, not after

`fetch.py` and `init.py` each grew their own near-identical `_run`
helper and exception class. Duplicating it once (in `init.py`) was a
deliberate, deferred decision -- premature abstraction from a single
example would have been guessing at the right shape. But `update.py`
and `deploy.py` are next, and both need the exact same
subprocess-running pattern; leaving the duplication in place at this
point would have meant going from two copies to four, a meaningfully
worse place to do this refactor from. `run_git` now lives in
`_gitutil.py`; each caller (`fetch.py`'s `_run`, `init.py`'s `_run`,
`update.py`'s `_git`) is a thin wrapper that translates the shared
`GitCommandError` into its own command-specific exception type
(`FetchNotesError`, `InitError`, `UpdateError`), preserving every
existing test's `pytest.raises`/`patch` assertions unchanged.

`_gitutil.py` also holds `coursecraft_env()`, which returns the
environment dict that every internal git commit needs: `COURSECRAFT_INTERNAL=1`
(required by `course/`'s pre-commit hook) plus a consistent
`GIT_AUTHOR_NAME`/`EMAIL` / `GIT_COMMITTER_NAME`/`EMAIL` identity.
Sharing this from one place means `init` and `update` can never drift
out of sync on what the hook expects.

A text spinner (`run_git_with_spinner`) was added here briefly and then
removed -- it ran `git clone` in a background thread while printing
cycling ellipsis dots, to make a slow clone visibly not-hung. Removed
because: it added threading complexity, the spinner required its runner
to be passed as a parameter (so the caller's `_run` wrapper was still
called inside the background thread, not `run_git` directly -- a real
regression found before shipping), and ultimately the UX gain of a
spinner over a silent wait wasn't worth the machinery.

## `instrument.py`: wraps sections, nothing else, and is course.yml-independent

`instrument()` wraps every labeled `##` heading (in a chapter or
appendix -- exercises/inserts are never touched, since they have no
independent visibility of their own) in a flat
`:::{.content-hidden unless-meta="sections.<label>"}` div. Deliberately
**every** labeled section, not just ones some lecture names in its
`sections` list: instrumentation gives every section a `sections.*`
hook regardless of whether `course.yml` ever mentions it -- a section
omitted from every lecture's list simply has its hook set `false` in
every profile and remains hidden. This is what makes `instrument()` a pure function of the
notes content alone, with **no dependency on `course.yml` at all** --
the metadata *values* (which hooks are true for a given profile) are
decided later, during profile generation.

This is a straightforward reuse of `structure.py`'s fence-aware
heading detection (a decorative `##` title inside a `.theorem`/
`.lproof` div is correctly never mistaken for a real section
boundary), not new parsing logic -- the only new part is the actual
wrapping. Verified against real content, not just the synthetic unit
tests: instrumented the real `logic-notes` Chapter 1, rendered it with
every `sections.*` key set `true`, and confirmed **100% text
similarity** against the uninstrumented original -- instrumentation
changes nothing when everything is revealed. Separately, set some
keys `false` and confirmed with the same "grep the rendered HTML for
section-unique text" method used throughout this project that hiding
is real content removal, not CSS: hidden sections are genuinely absent
from the output. Also ran `instrument()` against the two real chapters
containing decorative theorem-title headings (`## Transitivity`, `##
Transmission`, both nested inside `.theorem` divs) and confirmed the
wrap count matches exactly the number of real labeled sections in each
-- the decorative headings weren't mistaken for section boundaries on
real content, not just in the hand-built test case.

## `.yml`, not `.yaml`

`course.yml`, `coursecraft.yml`, and (eventually) `toc.yml`/`site.yml`
all use the `.yml` extension, even though earlier drafts of this
project used `course.yaml`. The rename was purely a matter of which
direction was cheaper, not a strong opinion about the extension
itself: `coursecraft.yml` was already a live, committed file in the
real `logic-notes` repo on GitHub by the time this was noticed, while
`course.yaml` had only ever existed in test fixtures and sandbox
scaffolds -- so standardizing on `.yml` meant renaming a string
literal in this codebase, not migrating a file that already exists in
the wild.

## `structure.find_headings`: extracted before a fourth copy, not after

`lint.py` and `instrument.py` each had their own copy of the same
fence-aware heading scan. Rather than write a third copy for `toc.py`
(which needs the identical scan, just applied across a whole notes
repo instead of one file), the scan itself moved into `structure.py`
as `find_headings()`, returning every heading (optionally filtered by
level) with its line number, label (if any), and raw heading text.
`lint.find_unlabeled_sections` and `instrument.instrument` both became
thin filters over it -- confirmed behavior-preserving by running the
full suite unchanged immediately after the refactor, before writing
anything new on top of it. This is the same "extract now, before it
triples" reasoning as `_gitutil.py`, just one module earlier in the
chain than that one caught it.

## `toc.py`: ordered by `_quarto.yml`, not lexical filename order

`coursecraft toc` builds `./toc.yml` from `./notes` -- every chapter
and appendix, in the order declared by `notes/_quarto.yml`'s own
`book: chapters:`/`appendices:` list, each with its labeled `##`
sections in document order. Deliberately **not** lexical filename
order: that would impose a numbering convention on every notes repo
that adopts `coursecraft`, and would silently mis-order the moment
padding is inconsistent (`1-foo.qmd` sorting before `10-bar.qmd`).
`_quarto.yml`'s list is a signal the notes repo's author already has
to get right for an unrelated reason -- it's what `quarto preview`
itself uses -- so this reuses it rather than asking for a second,
redundant one. Confirmed with a test fixture built specifically so
lexical order would give the *wrong* answer (files named `zebra.qmd`/
`apple.qmd` but declared in the opposite order), and separately
against the real `logic-notes` repo, where the output matched every
real chapter/section title and label exactly -- including the
`sec-induction-proof-by-induction` rename from much earlier in this
project, confirming this reflects the repo's current real state, not
a stale assumption.

Takes **no arguments at all** -- always `./notes`, erroring
(`toc failed: 'notes' not found.`) if it doesn't exist. This was a
deliberate correction: an earlier draft gave it an optional repo-root
argument by analogy with `validate-notes`, but `validate-notes` has a
genuine standalone use case (running against any notes repo during
development) that `toc` doesn't share -- its only purpose is helping
populate *this* section's `course.yml`, which only makes sense inside
a section folder. An optional argument would have reopened exactly the
"ran a command against the wrong directory with no signal anything
was off" footgun `fetch-notes`'s own required-`course.yml` check was
built to close.

An entry in `_quarto.yml`'s list that doesn't match the manifest's
`chapter_glob`/`appendix_dir_glob` (a front-matter `index.qmd`, most
commonly) is silently excluded, cross-referencing the two signals
(order from `_quarto.yml`, membership from `coursecraft.yml`'s globs)
rather than hardcoding "skip index.qmd" as a special case.

`toc.yml` is written beside `course.yml`, never inside `notes/` --
`notes/` is a git clone that gets pushed back to the master repo via
sync-back, and a stray generated file there could get committed and
pushed upstream by accident. Unlike `course.yml`, it always
overwrites: it's 100% derived from `notes/`, so there's nothing to
protect, and rerunning it after editing `notes/` should just produce
a fresh, correct file every time. `update` will call the same
`build_toc()`/`write_toc_yaml()` functions as a side effect of its own
validation step (check A uses `label_positions()` to verify that every
label in `lec.sections` exists in the notes), so `toc.yml` stays fresh
automatically on every `update` run without `update` needing to read
it back as a dependency -- `coursecraft toc` remains useful standalone
for the one moment that matters between `update` runs: refreshing the
outline right before reopening the wizard mid-term to add a new
lecture referencing newly-written content.

Only a flat `book: chapters:`/`appendices:` list is supported for
now -- a `part:` grouping raises a clear error rather than silently
mis-ordering or crashing. `logic-notes`'s own `_quarto.yml` is flat
today, so this doesn't bite yet, but a portable tool should handle
the nested case eventually rather than assume every adopting notes
repo stays flat forever.

## `update`: the ten-step flow, and why course/ is never half-updated

`update` either fully succeeds or leaves `course/` exactly as it was
before -- this is the property the step ordering is designed to protect.
Steps 1-3 (build toc, write toc.yml, validate) all run before step 4
(unlock course/) touches anything. If validation fails, the directory
is never unlocked; a second call to `update` with a corrected
`course.yml` finds `course/` unchanged and starts fresh.

The ten steps:

1. **Build toc** -- scan `notes/` by walking `_quarto.yml`'s chapter
   list. Never reads `toc.yml` off disk; always derives from source.
2. **Write toc.yml** -- side effect of step 1; used externally by the
   course-yaml wizard. `update` itself uses the in-memory `toc_data`
   for all subsequent steps, never reads toc.yml back.
3. **Validate** -- `CourseConfig.from_yaml` + A/B/C course checks.
   Abort before touching course/ if anything is wrong.
4. **Unlock** -- `chmod 0o644` everything in `course/`. No-op on first
   run (files already writable); removes the read-only protection from
   the previous run so steps 5-8 can write.
5. **Copy + instrument** -- `notes/` → `course/`, with chapter/appendix
   `.qmd` files instrumented in-flight (labeled `##` sections wrapped
   in `content-hidden` divs). Everything else verbatim. Exclusions:
   render output dirs, notes-repo metadata (`.gitignore`, `README.md`,
   `coursecraft.yml`, `.pre-commit-config.yaml`), pre-existing profile
   YAMLs, and `index.qmd` (overwritten by step 8).
5b. **Strip base `_quarto.yml`** -- the copied `_quarto.yml` is
   trimmed to `chapters: [index.qmd]` with no appendices. Each profile
   (step 7) appends exactly the chapters and appendices that have
   visible content for its date, rather than the full list from the
   notes repo (which would render empty invisible chapters for every
   profile before those chapters are reached).
6. **Generate hw/exam files** -- `hw-NN.qmd` and `hw-NN-solutions.qmd`
   per assignment, using `macros_include` from the manifest.
7. **Generate profiles** -- one `_quarto-<date>.yml` per timeline
   moment (see Profile-break rule above).
8. **Generate syllabus** -- writes `course/index.qmd`.
9. **Lock** -- `chmod 0o444` everything in `course/`. Local safeguard
   against accidental hand-editing; git doesn't preserve this bit, so
   it has no effect on CI or a fresh clone.
10. **Commit** -- `git add -A && git commit` in `course/`, using
    `coursecraft_env()`. Skipped (without error) if nothing is staged
    after step 9 (i.e., notes and course.yml haven't changed since the
    last run). The commit is guarded by `course/`'s pre-commit hook,
    which rejects any commit not setting `COURSECRAFT_INTERNAL=1`.

## Profiles: Approach 1 (visible-chapters-per-profile)

The base `_quarto.yml` in `course/` holds only `chapters: [index.qmd]`
after step 5b strips it. Each profile's `book.chapters` list contains
exactly the chapters that have visible content for that date (i.e., at
least one section label in the visible set for that moment, or the
chapter label itself is visible). Quarto's profile merge appends the
profile's `chapters` to the base's, so the effective chapter list for
a given date is `[index.qmd] + visible_chapters + hw_files`.

Why not keep all chapters in the base and use `content-hidden` alone
to gate sections? A chapter with no visible sections still renders as
an empty entry in the book nav -- visually confusing and hard to
explain. Excluding the file from the chapter list entirely is cleaner.

`_visible_chapters(visible, toc_data)` determines which chapters/
appendices have any visible content: a chapter is included if its own
chapter label or any of its section labels appears in the visible set.
Hw files always go at the end of `book.chapters` (not appendices) and
are unnumbered via `# Homework N {.unnumbered}` -- no `title:` in
frontmatter, which would create a duplicate heading and break Quarto's
unnumbered detection.

`_sections_metadata(visible, toc_data)` builds the per-profile
`metadata: sections:` dict. It automatically sets any chapter label to
`true` whenever at least one of its subsection labels is in the visible
set -- so the chapter's own `##`-heading wrapper (instrumented the same
way as any section) is never hidden while content from that chapter is
being shown.

## Syllabus: schedule grouped by chapter

`syllabus.py` builds `course/index.qmd` with a course-info table, a
schedule section (if any lectures are defined), and an assignments
table. The schedule groups lectures under `### Chapter Title` headings
that change whenever the chapter of the current lecture's first section
label changes. The topic for each lecture is derived from
`lec.sections[0]` (the first label in the lecture's `sections` list).
A chapter-level first label shows "Introduction" rather than repeating
the chapter title that already appears in the `###` heading.
`Lecture.name` overrides the derived topic when set.

## Planned extensions

These aren't designed yet -- listed here so the design decisions made
so far can be evaluated against them before they conflict.

- **Web interface for course.yml editing and new-notes creation.** A
  Django (or similar) backend importing the same `CourseConfig` and
  `NotesManifest` Pydantic models, so form validation and YAML
  validation are the same code, not a second copy. YAML on disk remains
  the durable source of truth; the UI edits/generates the file, it
  doesn't replace it with a DB representation. `model_json_schema()`
  export (free from Pydantic) means a JSON-Schema-driven form library
  can generate a working form directly from the model. The web backend
  would also orchestrate `coursecraft update` (or call `update()`
  directly) rather than the instructor running it manually.

- **Interactive exercise submission.** Students answer online; a due
  date disables submission rather than just triggering solution reveal.
  Requires a real backend injecting into Quarto output. The schema's
  `due` field is already positioned to support this without rework --
  it's kept distinct from `show_solutions` timing precisely so a
  submission-deadline feature has a date to attach to without having to
  un-conflate anything retroactively.

- **Student auth and access control.** Genuinely different from
  date-gating (stops an unenrolled outsider seeing anything, vs. an
  enrolled student seeing something too early). Deferred until the web
  interface exists to manage it, since access control without an admin
  UI is unlikely to be usable anyway.

- **Online VS Code editor for notes.** An `openvscode-server` or
  similar instance giving instructors a browser-based editor over the
  cloned `notes/` directory with pre-commit hooks active and a
  "push and update" button. The pre-commit hooks (reflow, lint) are
  already in the notes repo; the infrastructure question is hosting
  and auth, not what the hooks should do.

## Package structure

```
src/coursecraft/
├── structure.py    # fence-aware heading/label/list parsing; find_headings()
├── reflow.py       # the formatting engine, built on structure.py
├── lint.py         # missing-label detection (report only)
├── schema.py       # course.yml: CourseConfig / Lecture / Assignment Pydantic
│                   # models + validators; Lecture.name for custom syllabus topics
├── manifest.py     # coursecraft.yml: NotesManifest / Conventions Pydantic model
├── repo_checks.py  # checks a real notes repo's content against its manifest
├── course_checks.py # A/B/C/D cross-checks between course.yml and notes/
├── _gitutil.py     # run_git(), coursecraft_env() -- shared by all git ops
├── fetch.py        # fetch-notes: clone → branch → push → pre-commit install
├── init.py         # init: scaffold course/ git repo + placeholder course.yml
├── instrument.py   # wraps ## sections in content-hidden divs
├── toc.py          # build_toc() ordered by notes/_quarto.yml; label_positions() used by check A
├── hw.py           # generate hw-NN.qmd / hw-NN-solutions.qmd per assignment
├── profiles.py     # generate _quarto-<date>.yml per timeline moment
├── syllabus.py     # generate course/index.qmd
├── update.py       # orchestrates all 10 update steps
└── cli.py          # thin argparse wrapper over all commands
```

`cli.py` is intentionally thin -- every real function is directly
importable (`from coursecraft.schema import CourseConfig`,
`from coursecraft import reflow`, `from coursecraft import update`), so
a future web backend or test suite calls the same code the CLI does,
never a CLI subprocess wrapper around logic that only exists inside
`if __name__ == "__main__"`.

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

`cli.py` went untested at the direct level for longer than everything
else -- it's thin wiring over already-tested modules, so each new
subcommand was verified live/manually instead. `test_cli.py` closes
that gap once `cli.py` had grown to six subcommands, and immediately
caught a real bug on its first run (in the test file itself, not
`cli.py`: a fixture-setup test forgot to create a parent directory
before populating it) -- a small reminder that "this file has never
had a bug" and "this file has never been tested" aren't the same
claim. Real execution is used everywhere it's safe and fast (every
subcommand except `fetch-notes`, which is mocked specifically to keep
the test suite from making real network calls); `init`, being local
and already covered thoroughly at the library level, is still run for
real here too, since these tests are about the wiring on top of it,
not re-proving `init()` itself works.
