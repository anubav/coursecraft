# coursecraft

Generates section-specific course sites from a `logic-notes`-style
master notes repo: syllabi, homework/exam pages, per-lecture content
profiles, and (eventually) a deployment pipeline -- all driven by a
single `course.yaml` per section.

## Install

```
pip install git+https://github.com/<your-username>/coursecraft.git
```

For development (editable install, so local changes take effect
immediately without reinstalling):
```
git clone https://github.com/<your-username>/coursecraft.git
cd coursecraft
pip install -e .
```

## Usage

```
coursecraft reflow <paths...>          # reformat .qmd files in place
                                        # (semantic linebreaks by default)
coursecraft reflow --check <paths...>  # report only, exit nonzero if any
                                        # file isn't already formatted
coursecraft lint <paths...>            # check for ## headings missing a
                                        # {#sec-...} label (report only --
                                        # never guesses a name for you)
coursecraft validate <course.yaml>     # validate a section's course.yaml
coursecraft validate-notes [repo-root] # validate a notes repo's
                                        # coursecraft.yml manifest, and
                                        # check its actual content:
                                        # globs match real files, every
                                        # chapter/appendix has exactly
                                        # one labeled heading, no
                                        # duplicate {#label}s anywhere,
                                        # no dangling {{< include >}}s
coursecraft fetch-notes                # clone the notes repo (and
                                        # branch) declared in
                                        # ./course.yaml into ./notes,
                                        # on a fresh section/<name>
                                        # branch (pushed immediately),
                                        # then run validate-notes.
                                        # Requires a valid course.yaml
                                        # in the current directory --
                                        # this is also what stops
                                        # fetch-notes from running
                                        # accidentally inside an
                                        # already-cloned notes/
coursecraft init <notes-repo-url>      # create ./course/ (a fresh,
                                        # protected git repo -- direct
                                        # commits into it are rejected
                                        # by a pre-commit hook) and, if
                                        # missing, a placeholder
                                        # ./course.yaml with a real
                                        # notes_repo but every other
                                        # required field set to
                                        # REPLACE_ME
```

## Status

Implemented: formatting (`reflow`), label linting (`lint`),
`course.yaml` validation (`validate`), notes-repo manifest validation
(`validate-notes`), cloning a notes repo onto a fresh section branch
(`fetch-notes`), and scaffolding a section's `course/` repo plus a
placeholder `course.yaml` (`init`). Not yet built: `update`, `deploy`,
or the `build` command that wraps `init` -> `fetch-notes` -> (a future
`course.yaml`-filling wizard) -> `update` -> `deploy` together.

## Roadmap

Deliberate deferrals -- not forgotten, just not worth building before
there's a real need. See `ARCHITECTURE.md` for the reasoning behind
each of these.

- [ ] **Label-ordering sanity check for `update`.** The A/B/C checks
      `update` will run (do `course.yaml`'s `notes_start`/`notes_end`
      labels and assigned exercise names still exist in `notes/`) only
      catch a label that's missing entirely, not one that exists but
      is out of order -- e.g. a `notes_end` typo'd to point at content
      *earlier* in the book than an already-covered lecture. Needs real
      machinery (each label's absolute position across the whole
      ordered chapter+appendix tree), not just an existence check.
- [ ] **`appendix_marker_class` in the manifest.** `check_chapter_headings`
      currently only enforces `chapter_marker_class` for `chapter_glob`
      matches, since the manifest has no equivalent field for an
      appendix's own marker class (`logic-notes` uses `.appendix`, but
      nothing declares that convention anywhere). Either add the field
      or decide the check shouldn't need it.
- [ ] **`coursecraft sync-back`.** Automating the branch -> commit ->
      push -> open-PR sequence for returning a term's edited `notes/`
      to the master repo. Plain git works fine for this today; only
      worth automating if the manual sequence becomes actual friction.
- [ ] **Student roster / access control** on deployed section sites.
      Waiting on the web interface that would actually administer it --
      access control with no UI to manage it isn't very usable anyway.
- [ ] **Interactive homework submission**, with a due date that cuts
      off submission rather than (or in addition to) revealing
      solutions. Needs a real backend (e.g. Django) injecting into the
      Quarto output. `Assignment.due` is already a distinct field from
      `show_solutions`'s reveal timing specifically so this can be
      added without reworking the schema later.
- [ ] **Web UI for generating `course.yaml`.** `CourseConfig` is
      already Pydantic (see "schema as a public API" in
      `ARCHITECTURE.md`), so this is mostly a frontend problem
      whenever it happens, not a schema one.
