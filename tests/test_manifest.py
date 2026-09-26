import copy

import pytest
from pydantic import ValidationError

from coursecraft.manifest import NotesManifest


@pytest.fixture
def base_manifest() -> dict:
    return {
        "coursecraft_spec": "1.0",
        "conventions": {
            "chapter_glob": "chapters/*.qmd",
            "appendix_dir_glob": "appendices/*.qmd",
            "exercise_glob": "exercises/*.qmd",
            "insert_glob": "inserts/**/*.qmd",
        },
    }


class TestValidManifest:
    def test_base_manifest_loads(self, base_manifest):
        manifest = NotesManifest.model_validate(base_manifest)
        assert manifest.coursecraft_spec == "1.0"
        assert manifest.conventions.chapter_glob == "chapters/*.qmd"

    def test_defaults_applied(self, base_manifest):
        manifest = NotesManifest.model_validate(base_manifest)
        assert manifest.conventions.label_prefix == "sec-"
        assert manifest.conventions.chapter_marker_class == "chapter"
        assert manifest.conventions.raw_text_div_classes == ["lproof"]
        assert manifest.conventions.macros_include is None

    def test_explicit_values_override_defaults(self, base_manifest):
        data = copy.deepcopy(base_manifest)
        data["conventions"]["label_prefix"] = "s-"
        data["conventions"]["raw_text_div_classes"] = ["lproof", "verbatim"]
        manifest = NotesManifest.model_validate(data)
        assert manifest.conventions.label_prefix == "s-"
        assert manifest.conventions.raw_text_div_classes == ["lproof", "verbatim"]


class TestSpecVersion:
    def test_supported_version_accepted(self, base_manifest):
        NotesManifest.model_validate(base_manifest)  # should not raise

    def test_unsupported_version_rejected(self, base_manifest):
        data = copy.deepcopy(base_manifest)
        data["coursecraft_spec"] = "2.0"
        with pytest.raises(ValidationError, match="not supported"):
            NotesManifest.model_validate(data)


class TestTypoDetection:
    def test_typo_in_convention_field_rejected(self, base_manifest):
        """A typo'd field name (e.g. 'exercize_glob') must be caught
        immediately, not silently ignored while exercise_glob falls
        back to being reported as simply missing."""
        data = copy.deepcopy(base_manifest)
        data["conventions"]["exercize_glob"] = data["conventions"].pop("exercise_glob")
        with pytest.raises(ValidationError) as exc_info:
            NotesManifest.model_validate(data)
        errors = {e["type"] for e in exc_info.value.errors()}
        assert "extra_forbidden" in errors

    def test_typo_at_top_level_rejected(self, base_manifest):
        data = copy.deepcopy(base_manifest)
        data["coursecraft_specc"] = data.pop("coursecraft_spec")
        with pytest.raises(ValidationError):
            NotesManifest.model_validate(data)

    def test_missing_required_field_rejected(self, base_manifest):
        data = copy.deepcopy(base_manifest)
        del data["conventions"]["insert_glob"]
        with pytest.raises(ValidationError, match="Field required"):
            NotesManifest.model_validate(data)
