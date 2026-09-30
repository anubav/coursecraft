"""
coursecraft deploy -- generates .github/workflows/deploy.yml in course/.

Run once to set up CI deployment to GitHub Pages. After that, pushing
course/ to GitHub (via `coursecraft update --push`) triggers the workflow
automatically on every push and nightly at 06:00 UTC.

The workflow:
  1. Checks out the course/ repo
  2. (Optional) checks out the private solutions repo into solutions/
     using a deploy key stored as SOLUTIONS_DEPLOY_KEY secret
  3. Finds all _quarto-<date>.yml profiles whose date <= today
  4. Renders each active profile with Quarto (output: _book/<date>/)
  5. Generates a root index.html redirect to the latest active profile
  6. Uploads _book/ as a GitHub Pages artifact and deploys

The rendered HTML is what's public -- source .qmd files (including
solutions includes) are never exposed.
"""

from pathlib import Path
from typing import Optional


# Solutions checkout step -- only included when solutions_repo is given.
_SOLUTIONS_STEP = """\
      - name: Checkout solutions
        uses: actions/checkout@v4
        with:
          repository: {solutions_repo}
          ssh-key: ${{{{ secrets.SOLUTIONS_DEPLOY_KEY }}}}
          path: solutions
"""

_WORKFLOW_TEMPLATE = """\
name: Deploy course site

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 6 * * *'

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{{{ steps.deployment.outputs.page_url }}}}
    steps:
      - name: Checkout course
        uses: actions/checkout@v4
{solutions_step}
      - name: Set up Quarto
        uses: quarto-dev/quarto-actions/setup@v2

      - name: Find active profiles
        id: profiles
        run: |
          python3 - <<'EOF'
          import json, os
          from datetime import date
          today = date.today()
          profiles = []
          for f in sorted(os.listdir('.')):
              if f.startswith('_quarto-') and f.endswith('.yml'):
                  stem = f[len('_quarto-'):-len('.yml')]
                  try:
                      if date.fromisoformat(stem) <= today:
                          profiles.append(stem)
                  except ValueError:
                      pass
          latest = profiles[-1] if profiles else ''
          manifest = {{}}
          if os.path.exists('coursecraft-manifest.json'):
              with open('coursecraft-manifest.json') as f:
                  manifest = json.load(f)
          start = manifest.get(latest, '') if latest else ''
          with open(os.environ['GITHUB_OUTPUT'], 'a') as fh:
              fh.write(f'profiles={{json.dumps(profiles)}}\\n')
              fh.write(f'latest={{latest}}\\n')
              fh.write(f'start={{start}}\\n')
          EOF

      - name: Render active profiles
        if: steps.profiles.outputs.latest != ''
        env:
          PROFILES: ${{{{ steps.profiles.outputs.profiles }}}}
        run: |
          python3 - <<'EOF'
          import json, os, subprocess
          for p in json.loads(os.environ['PROFILES']):
              subprocess.run(['quarto', 'render', '--profile', p], check=True)
          EOF

      - name: Generate site root
        run: |
          mkdir -p _book
          LATEST="${{{{ steps.profiles.outputs.latest }}}}"
          START="${{{{ steps.profiles.outputs.start }}}}"
          ANCHOR=""
          [ -n "$START" ] && ANCHOR="#${{START}}"
          URL="./${{LATEST}}/${{ANCHOR}}"
          if [ -n "$LATEST" ]; then
            cat > _book/index.html <<HTML
          <!DOCTYPE html>
          <html><head>
          <meta http-equiv="refresh" content="0; url=${{URL}}">
          <script>window.location.replace('${{URL}}');</script>
          </head><body>Redirecting to current lecture...</body></html>
          HTML
          else
            cat > _book/index.html <<HTML
          <!DOCTYPE html>
          <html><head><title>Course not yet started</title></head>
          <body><p>The course site is not yet available.</p></body></html>
          HTML
          fi

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: _book

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
"""


class DeployError(Exception):
    pass


def _render_workflow(solutions_repo: Optional[str]) -> str:
    solutions_step = (
        _SOLUTIONS_STEP.format(solutions_repo=solutions_repo)
        if solutions_repo
        else ""
    )
    return _WORKFLOW_TEMPLATE.format(solutions_step=solutions_step)


def deploy(
    course_dir: str | Path = "course",
    solutions_repo: Optional[str] = None,
    force: bool = False,
) -> Path:
    """Generate .github/workflows/deploy.yml in course_dir.

    Returns the path to the created file. Raises DeployError if the file
    already exists and force is False, or if course_dir doesn't exist."""
    course_path = Path(course_dir)
    if not course_path.is_dir():
        raise DeployError(
            f"'{course_path}' not found -- run 'coursecraft init' first."
        )

    workflows_dir = course_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_path = workflows_dir / "deploy.yml"
    if workflow_path.exists() and not force:
        raise DeployError(
            f"'{workflow_path}' already exists. Use --force to overwrite."
        )

    if workflow_path.exists():
        workflow_path.chmod(0o644)
    workflow_path.write_text(_render_workflow(solutions_repo), encoding="utf-8")
    return workflow_path


def setup_instructions(
    solutions_repo: Optional[str] = None,
    course_repo: Optional[str] = None,
) -> str:
    """Return human-readable one-time setup instructions."""
    settings_base = (
        f"https://github.com/{course_repo}/settings"
        if course_repo
        else "https://github.com/<owner>/<course-repo>/settings"
    )
    lines = ["One-time setup:"]

    if solutions_repo:
        lines += [
            "",
            "Step 1 — Generate a deploy key pair (run outside your project directory):",
            "",
            "  ssh-keygen -t ed25519 -C coursecraft-deploy -f coursecraft_deploy_key",
            "",
            "  This creates coursecraft_deploy_key (private) and",
            "  coursecraft_deploy_key.pub (public). Delete both files when done.",
            "",
            f"Step 2 — Add the public key to {solutions_repo}:",
            "",
            f"  https://github.com/{solutions_repo}/settings/keys",
            "  → Add deploy key",
            "  → Title: coursecraft deploy",
            "  → Key: paste contents of coursecraft_deploy_key.pub",
            "  → Allow write access: No",
            "",
            "Step 3 — Add the private key as a secret on the course repo:",
            "",
            f"  {settings_base}/secrets/actions",
            "  → New repository secret",
            "  → Name: SOLUTIONS_DEPLOY_KEY",
            "  → Value: paste entire contents of coursecraft_deploy_key",
            "           (including the -----BEGIN/END----- lines)",
            "",
            "Step 4 — Enable Pages on the course repo:",
        ]
    else:
        lines += [
            "",
            "Step 1 — Enable Pages on the course repo:",
        ]

    lines += [
        "",
        f"  {settings_base}/pages",
        "  → Source: GitHub Actions",
        "",
        "Then push course/ to trigger the first deploy:",
        "",
        "  coursecraft update --push",
        "  (or: cd course && git push)",
    ]

    return "\n".join(lines)
