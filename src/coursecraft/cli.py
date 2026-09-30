import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from .reflow import reflow
from .lint import find_unlabeled_sections
from .schema import CourseConfig
from .manifest import NotesManifest
from .repo_checks import run_all_checks
from .fetch import fetch_notes, FetchNotesError
from .init import init, InitError
from .toc import build_toc, write_toc_yaml, TocError
from .course_checks import run_course_checks
from .update import update, UpdateError
from .deploy import deploy, DeployError, setup_instructions


def _cmd_reflow(args) -> int:
    needs_changes = []
    for path_str in args.paths:
        p = Path(path_str)
        original = p.read_text(encoding='utf-8')
        updated = reflow(original, width=args.width)
        if updated != original:
            needs_changes.append(str(p))
            if not args.check:
                p.write_text(updated, encoding='utf-8')

    if needs_changes:
        verb = 'would be reflowed' if args.check else 'reflowed'
        print(f'The following files {verb} (semantic linebreaks):')
        for c in needs_changes:
            print(f'  {c}')
        return 1
    return 0


def _cmd_lint(args) -> int:
    any_violations = False
    for path_str in args.paths:
        p = Path(path_str)
        text = p.read_text(encoding='utf-8')
        violations = find_unlabeled_sections(text)
        if violations:
            any_violations = True
            print(f'{p}:')
            for v in violations:
                print(f'  line {v.line_number}: "## {v.heading_text}" has no {{#sec-...}} label')
    if any_violations:
        return 1
    return 0


def _cmd_validate(args) -> int:
    try:
        config = CourseConfig.from_yaml(args.path)
    except ValidationError as e:
        print(f'{args.path}: INVALID\n')
        print(e)
        return 1
    n_lec = len(config.lectures)
    n_asn = len(config.assignments)
    print(f'{args.path}: OK -- {n_lec} lecture(s), {n_asn} assignment(s)')
    for i, lec in enumerate(config.lectures):
        mode = 'cumulative' if lec.cumulative else 'windowed'
        sections_str = ', '.join(lec.sections) if lec.sections else '(none)'
        print(f'  {config.lecture_name(i)}: {lec.date} [{sections_str}] ({mode})')
    for a in config.assignments:
        kind = 'exam' if a.is_exam else 'homework'
        sol = 'with solutions' if a.show_solutions else 'no solutions'
        print(f'  {a.name} [{kind}]: assigned {a.assigned}, due {a.due} ({sol})')

    if not args.notes:
        return 0

    notes_root = Path(args.notes)
    try:
        toc_data = build_toc(notes_root)
    except TocError as e:
        print(f'validate: could not build toc from {notes_root}: {e}')
        return 1

    results = run_course_checks(config, notes_root, toc_data)
    any_problems = any(results.values())
    if any_problems:
        print(f'\n{args.path}: notes checks FAILED')
        for check_name, problems in results.items():
            for p in problems:
                print(f'  [{check_name}] {p}')
        return 1

    print('  notes checks: OK (labels exist, exercises exist, solutions exist)')
    return 0


def _cmd_validate_notes(args) -> int:
    repo_root = Path(args.path)
    manifest_path = repo_root / 'coursecraft.yml'
    if not manifest_path.exists():
        print(f'{manifest_path}: not found')
        return 1

    try:
        manifest = NotesManifest.from_yaml(manifest_path)
    except ValidationError as e:
        print(f'{manifest_path}: INVALID\n')
        print(e)
        return 1

    results = run_all_checks(manifest, repo_root)
    any_problems = any(results.values())

    if any_problems:
        print(f'{manifest_path}: schema OK, but found problems:')
        for check_name, problems in results.items():
            for p in problems:
                print(f'  [{check_name}] {p}')
        return 1

    conv = manifest.conventions
    print(f'{manifest_path}: OK (coursecraft_spec {manifest.coursecraft_spec})')
    print(f'  {len(list(repo_root.glob(conv.chapter_glob)))} chapter file(s)')
    print(f'  {len(list(repo_root.glob(conv.appendix_dir_glob)))} appendix file(s)')
    print(f'  {len(list(repo_root.glob(conv.exercise_glob)))} exercise fragment(s)')
    print(f'  {len(list(repo_root.glob(conv.insert_glob)))} insert fragment(s)')
    print('  all checks passed: globs, chapter headings, labels, '
          'duplicate labels, includes')
    return 0


def _cmd_fetch_notes(args) -> int:
    course_yaml = Path('course.yml')
    if not course_yaml.exists():
        print('fetch-notes failed: no course.yml found in the current directory.')
        return 1

    try:
        course_info = CourseConfig.load_course_info(course_yaml)
    except ValidationError as e:
        print(f'{course_yaml}: INVALID\n')
        print(e)
        return 1

    try:
        target, branch = fetch_notes(
            repo_url=course_info.notes_repo,
            source_branch=course_info.notes_branch,
            branch=args.branch,
            target_dir=args.target,
        )
    except FetchNotesError as e:
        print(f'fetch-notes failed: {e}')
        return 1

    src_note = f" (branch {course_info.notes_branch!r})" if course_info.notes_branch else ""
    print(f'Cloned {course_info.notes_repo}{src_note} -> {target} '
          f'on branch {branch!r} (pushed)')

    hooks_active = (target / ".git" / "hooks" / "pre-commit").exists()
    if (target / ".pre-commit-config.yaml").exists():
        if hooks_active:
            print('pre-commit hooks installed.')
        else:
            print(
                'Warning: pre-commit hooks not installed. '
                f"Run 'pre-commit install' in {target}/ to enable them."
            )

    manifest_path = target / 'coursecraft.yml'
    if not manifest_path.exists():
        print(f'{manifest_path}: not found -- skipping validate-notes')
        return 0

    try:
        manifest = NotesManifest.from_yaml(manifest_path)
    except ValidationError as e:
        print(f'{manifest_path}: INVALID\n')
        print(e)
        return 1
    results = run_all_checks(manifest, target)
    any_problems = any(results.values())
    if any_problems:
        print('validate-notes found problems:')
        for check_name, problems in results.items():
            for p in problems:
                print(f'  [{check_name}] {p}')
        return 1

    print('validate-notes: OK')
    return 0


def _cmd_init(args) -> int:
    try:
        course_path, wrote_yaml = init(
            notes_repo=args.notes_repo, notes_branch=args.notes_branch,
        )
    except InitError as e:
        print(f'init failed: {e}')
        return 1

    print(f"Created '{course_path}'.")
    print('Created course.yml.' if wrote_yaml else 'course.yml already exists.')
    return 0


def _cmd_toc(args) -> int:
    notes_path = Path('notes')
    if not notes_path.exists():
        print("toc failed: 'notes' not found.")
        return 1

    try:
        toc_data = build_toc(notes_path)
    except TocError as e:
        print(f'toc failed: {e}')
        return 1

    write_toc_yaml(toc_data)
    n_chapters = len(toc_data['chapters'])
    n_appendices = len(toc_data['appendices'])
    print(f'Wrote toc.yml ({n_chapters} chapter(s), {n_appendices} appendix(es)).')
    return 0


def _cmd_update(args) -> int:
    try:
        update(push=args.push, lock=not args.no_lock)
    except UpdateError as e:
        print(f'update failed: {e}')
        return 1
    print('update: OK')
    return 0


def _cmd_deploy(args) -> int:
    try:
        workflow_path = deploy(
            solutions_repo=args.solutions_repo,
            force=args.force,
        )
    except DeployError as e:
        print(f'deploy failed: {e}')
        return 1
    print(f"Wrote '{workflow_path}'.")
    print()
    print(setup_instructions(
        solutions_repo=args.solutions_repo,
        course_repo=args.course_repo,
    ))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog='coursecraft')
    sub = parser.add_subparsers(dest='command', required=True)

    reflow_p = sub.add_parser(
        'reflow',
        help='Reflow .qmd files in place (semantic-linebreak mode by '
             'default). Used both as a pre-commit hook and, with '
             '--check, as a CI gate.',
    )
    reflow_p.add_argument('paths', nargs='+', help='Paths to .qmd files')
    reflow_p.add_argument('--width', type=int, default=None,
                           help='Column-wrap width. Omit for semantic-'
                                'linebreak mode (one sentence per line).')
    reflow_p.add_argument('--check', action='store_true',
                           help="Don't modify files; exit nonzero if any "
                                "file is not already correctly formatted.")
    reflow_p.set_defaults(func=_cmd_reflow)

    lint_p = sub.add_parser(
        'lint',
        help='Check for top-level ## headings missing a {#sec-...} '
             'label. Reports only -- never writes a label itself.',
    )
    lint_p.add_argument('paths', nargs='+', help='Paths to .qmd files')
    lint_p.set_defaults(func=_cmd_lint)

    validate_p = sub.add_parser(
        'validate',
        help='Validate a course.yml file and summarize its schedule. '
             'Pass --notes to also check labels, exercises, solutions, '
             'and lecture ordering against a real notes repo.',
    )
    validate_p.add_argument('path', help='Path to course.yml')
    validate_p.add_argument(
        '--notes', default=None, metavar='DIR',
        help='Path to a notes repo root; enables A/B/C/D cross-checks '
             'against real content (labels exist, exercises exist, '
             'solutions exist, label ordering is non-decreasing).',
    )
    validate_p.set_defaults(func=_cmd_validate)

    validate_notes_p = sub.add_parser(
        'validate-notes',
        help="Validate a notes repo's coursecraft.yml manifest and "
             'confirm its globs actually match real files.',
    )
    validate_notes_p.add_argument(
        'path', nargs='?', default='.',
        help='Path to the notes repo root (default: current directory)',
    )
    validate_notes_p.set_defaults(func=_cmd_validate_notes)

    fetch_notes_p = sub.add_parser(
        'fetch-notes',
        help='Clone the notes repo declared in ./course.yml into '
             './notes on a fresh section/<name> branch (pushed '
             'immediately), then run validate-notes. Requires a valid '
             'course.yml in the current directory.',
    )
    fetch_notes_p.add_argument(
        '--branch', default=None,
        help='Name for the new section branch (default: section/<current directory name>)',
    )
    fetch_notes_p.add_argument(
        '--target', default='notes',
        help='Directory to clone into (default: notes)',
    )
    fetch_notes_p.set_defaults(func=_cmd_fetch_notes)

    init_p = sub.add_parser(
        'init',
        help='Create ./course/ (a fresh, protected git repo) and, if '
             'missing, a placeholder ./course.yml.',
    )
    init_p.add_argument('notes_repo', help='URL of the notes repo for course.yml')
    init_p.add_argument(
        '--notes-branch', default=None,
        help='Branch of the notes repo (default: its own default branch)',
    )
    init_p.set_defaults(func=_cmd_init)

    toc_p = sub.add_parser(
        'toc',
        help='Build ./toc.yml from ./notes, ordered by '
             'notes/_quarto.yml (not lexical filename order).',
    )
    toc_p.set_defaults(func=_cmd_toc)

    update_p = sub.add_parser(
        'update',
        help='Regenerate ./course/ from ./notes and ./course.yml '
             '(validates, copies, instruments). Requires both to exist.',
    )
    update_p.add_argument(
        '--push', action='store_true',
        help='Push course/ to its remote after committing.',
    )
    update_p.add_argument(
        '--no-lock', action='store_true',
        help='Leave course/ writable after update (skips step 9). '
             'Useful when you need to render or preview locally.',
    )
    update_p.set_defaults(func=_cmd_update)

    deploy_p = sub.add_parser(
        'deploy',
        help='Generate .github/workflows/deploy.yml in course/ to publish '
             'the course site to GitHub Pages. Run once; after that, push '
             'course/ to trigger the workflow.',
    )
    deploy_p.add_argument(
        '--solutions-repo', default=None, metavar='OWNER/REPO',
        help='Private solutions repo (e.g. owner/logic-solutions). When '
             'given, the workflow checks it out at render time using a '
             'SOLUTIONS_DEPLOY_KEY secret.',
    )
    deploy_p.add_argument(
        '--course-repo', default=None, metavar='OWNER/REPO',
        help='Course repo (e.g. owner/phil101). Used only in the setup '
             'instructions printed after the workflow file is written.',
    )
    deploy_p.add_argument(
        '--force', action='store_true',
        help='Overwrite an existing deploy.yml.',
    )
    deploy_p.set_defaults(func=_cmd_deploy)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
