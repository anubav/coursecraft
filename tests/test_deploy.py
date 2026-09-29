import yaml
import pytest

from coursecraft.deploy import (
    deploy,
    DeployError,
    setup_instructions,
    _render_workflow,
)


# ---------------------------------------------------------------------------
# Workflow template
# ---------------------------------------------------------------------------

class TestRenderWorkflow:
    def test_output_is_valid_yaml(self):
        w = _render_workflow(None)
        data = yaml.safe_load(w)
        assert isinstance(data, dict)

    def test_output_with_solutions_is_valid_yaml(self):
        w = _render_workflow("owner/logic-solutions")
        data = yaml.safe_load(w)
        assert isinstance(data, dict)

    def test_github_actions_expression_syntax_present(self):
        w = _render_workflow(None)
        # GH Actions expression syntax must appear verbatim
        assert "${{ steps.deployment.outputs.page_url }}" in w

    def test_no_solutions_step_without_repo(self):
        w = _render_workflow(None)
        assert "Checkout solutions" not in w
        assert "SOLUTIONS_DEPLOY_KEY" not in w

    def test_solutions_step_included_when_repo_given(self):
        w = _render_workflow("owner/logic-solutions")
        assert "Checkout solutions" in w
        assert "owner/logic-solutions" in w
        assert "${{ secrets.SOLUTIONS_DEPLOY_KEY }}" in w

    def test_pages_deploy_step_present(self):
        w = _render_workflow(None)
        assert "actions/deploy-pages" in w

    def test_upload_pages_artifact_step_present(self):
        w = _render_workflow(None)
        assert "actions/upload-pages-artifact" in w

    def test_quarto_setup_step_present(self):
        w = _render_workflow(None)
        assert "quarto-dev/quarto-actions/setup" in w

    def test_nightly_schedule_present(self):
        w = _render_workflow(None)
        assert "schedule:" in w
        assert "cron:" in w

    def test_github_actions_expressions_well_formed(self):
        """GH Actions expressions must appear as ${{ ... }}, not ${{{{ ... }}}}."""
        w = _render_workflow(None)
        # Triple-brace sequences would indicate an un-resolved escape
        assert "${{{{" not in w
        assert "}}}}" not in w

    def test_bash_variable_syntax_present(self):
        """Bash variables for redirect must appear for bash expansion."""
        w = _render_workflow(None)
        assert "${LATEST}" in w
        assert "${START}" in w
        assert "${URL}" in w

    def test_start_output_written_in_find_profiles_step(self):
        w = _render_workflow(None)
        assert "start=" in w
        assert "coursecraft-manifest.json" in w

    def test_anchor_applied_conditionally(self):
        w = _render_workflow(None)
        assert 'ANCHOR="#${START}"' in w

    def test_concurrency_group_present(self):
        w = _render_workflow(None)
        assert "concurrency:" in w
        assert "group: pages" in w
        assert "cancel-in-progress: false" in w

    def test_pages_permissions_present(self):
        w = _render_workflow(None)
        assert "pages: write" in w
        assert "id-token: write" in w

    def test_solutions_step_placeholder_resolved(self):
        """The {solutions_step} format placeholder must not appear literally."""
        w = _render_workflow(None)
        assert "{solutions_step}" not in w

    def test_solutions_step_placeholder_resolved_with_solutions(self):
        w = _render_workflow("owner/logic-solutions")
        assert "{solutions_step}" not in w


# ---------------------------------------------------------------------------
# deploy()
# ---------------------------------------------------------------------------

class TestDeploy:
    def test_creates_workflow_file(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        path = deploy(course_dir=course)
        assert path.exists()
        assert path.name == "deploy.yml"

    def test_workflow_file_is_in_github_workflows(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        path = deploy(course_dir=course)
        assert path.parent.name == "workflows"
        assert path.parent.parent.name == ".github"

    def test_raises_when_course_dir_missing(self, tmp_path):
        with pytest.raises(DeployError, match="not found"):
            deploy(course_dir=tmp_path / "no-such-dir")

    def test_raises_when_file_exists_and_no_force(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        deploy(course_dir=course)
        with pytest.raises(DeployError, match="already exists"):
            deploy(course_dir=course)

    def test_force_overwrites_existing_file(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        path = deploy(course_dir=course)
        path.write_text("old content", encoding="utf-8")
        deploy(course_dir=course, force=True)
        assert "old content" not in path.read_text(encoding="utf-8")

    def test_workflow_content_is_valid_yaml(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        path = deploy(course_dir=course)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_solutions_repo_included_when_given(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        path = deploy(course_dir=course, solutions_repo="owner/solutions")
        content = path.read_text(encoding="utf-8")
        assert "owner/solutions" in content
        assert "SOLUTIONS_DEPLOY_KEY" in content

    def test_no_solutions_content_without_solutions_repo(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        path = deploy(course_dir=course)
        content = path.read_text(encoding="utf-8")
        assert "SOLUTIONS_DEPLOY_KEY" not in content

    def test_returns_path_to_workflow_file(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        result = deploy(course_dir=course)
        assert isinstance(result, type(tmp_path))
        assert result.suffix == ".yml"

    def test_creates_workflows_dir_if_missing(self, tmp_path):
        course = tmp_path / "course"
        course.mkdir()
        assert not (course / ".github").exists()
        deploy(course_dir=course)
        assert (course / ".github" / "workflows").is_dir()


# ---------------------------------------------------------------------------
# setup_instructions()
# ---------------------------------------------------------------------------

class TestSetupInstructions:
    def test_no_solutions_starts_with_step_1_pages(self):
        text = setup_instructions()
        assert "Step 1" in text
        assert "Pages" in text

    def test_with_solutions_has_deploy_key_steps(self):
        text = setup_instructions(solutions_repo="owner/solutions")
        assert "SOLUTIONS_DEPLOY_KEY" in text
        assert "ssh-keygen" in text
        assert "Step 1" in text
        assert "Step 2" in text
        assert "Step 3" in text
        assert "Step 4" in text

    def test_with_solutions_includes_repo_name(self):
        text = setup_instructions(solutions_repo="owner/logic-solutions")
        assert "owner/logic-solutions" in text

    def test_with_course_repo_includes_settings_url(self):
        text = setup_instructions(course_repo="owner/phil101")
        assert "owner/phil101" in text

    def test_instructs_to_push_via_update(self):
        text = setup_instructions()
        assert "coursecraft update --push" in text
