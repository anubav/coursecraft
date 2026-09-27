import pytest
import yaml

from coursecraft.toc import build_toc, write_toc_yaml, TocError


def _write_manifest(root):
    (root / "coursecraft.yml").write_text(yaml.dump({
        "coursecraft_spec": "1.0",
        "conventions": {
            "chapter_glob": "chapters/*.qmd",
            "appendix_dir_glob": "appendices/*.qmd",
            "exercise_glob": "exercises/*.qmd",
            "insert_glob": "inserts/**/*.qmd",
        },
    }))


class TestQuartoOrderRespected:
    def test_order_follows_quarto_yml_not_lexical_sort(self, tmp_path):
        """The whole point of this design: filenames are chosen so
        lexical order would give zebra, apple -- but _quarto.yml says
        apple first. If this test passes, _quarto.yml's order is
        genuinely being used, not silently falling back to sorted()."""
        _write_manifest(tmp_path)
        (tmp_path / "chapters").mkdir()
        (tmp_path / "chapters" / "zebra.qmd").write_text(
            "# Apple Chapter {#sec-apple .chapter}\n"
        )
        (tmp_path / "chapters" / "apple.qmd").write_text(
            "# Zebra Chapter {#sec-zebra .chapter}\n"
        )
        (tmp_path / "_quarto.yml").write_text(yaml.dump({
            "book": {"chapters": ["chapters/zebra.qmd", "chapters/apple.qmd"]}
        }))

        toc = build_toc(tmp_path)

        assert [c["title"] for c in toc["chapters"]] == ["Apple Chapter", "Zebra Chapter"]

    def test_index_qmd_excluded_via_glob_crossref(self, tmp_path):
        """index.qmd is first in _quarto.yml's list but doesn't match
        chapter_glob -- must be silently excluded, not treated as a
        chapter with no sections."""
        _write_manifest(tmp_path)
        (tmp_path / "chapters").mkdir()
        (tmp_path / "chapters" / "one.qmd").write_text(
            "# Chapter One {#sec-one .chapter}\n"
        )
        (tmp_path / "index.qmd").write_text("# Front Page\n")
        (tmp_path / "_quarto.yml").write_text(yaml.dump({
            "book": {"chapters": ["index.qmd", "chapters/one.qmd"]}
        }))

        toc = build_toc(tmp_path)

        assert len(toc["chapters"]) == 1
        assert toc["chapters"][0]["title"] == "Chapter One"


class TestSectionsWithinChapter:
    def test_sections_in_document_order(self, tmp_path):
        _write_manifest(tmp_path)
        (tmp_path / "chapters").mkdir()
        (tmp_path / "chapters" / "one.qmd").write_text(
            "# Chapter One {#sec-one .chapter}\n\n"
            "## Second Written Second {#sec-one-second}\n\ntext\n\n"
            "## First Written... Wait\n\n"  # unlabeled -- must be skipped
            "## Actually Third {#sec-one-third}\n"
        )
        (tmp_path / "_quarto.yml").write_text(yaml.dump({
            "book": {"chapters": ["chapters/one.qmd"]}
        }))
        toc = build_toc(tmp_path)
        sections = toc["chapters"][0]["sections"]
        assert [s["label"] for s in sections] == ["sec-one-second", "sec-one-third"]

    def test_chapter_with_no_labeled_sections_has_empty_list(self, tmp_path):
        _write_manifest(tmp_path)
        (tmp_path / "chapters").mkdir()
        (tmp_path / "chapters" / "one.qmd").write_text(
            "# Chapter One {#sec-one .chapter}\n\ntext with no subsections\n"
        )
        (tmp_path / "_quarto.yml").write_text(yaml.dump({
            "book": {"chapters": ["chapters/one.qmd"]}
        }))
        toc = build_toc(tmp_path)
        assert toc["chapters"][0]["sections"] == []


class TestErrors:
    def test_missing_quarto_yml_raises(self, tmp_path):
        _write_manifest(tmp_path)
        with pytest.raises(TocError, match="_quarto.yml"):
            build_toc(tmp_path)

    def test_missing_manifest_raises(self, tmp_path):
        (tmp_path / "_quarto.yml").write_text(yaml.dump({"book": {"chapters": []}}))
        with pytest.raises(TocError, match="coursecraft.yml"):
            build_toc(tmp_path)

    def test_part_groupings_raise_clear_error(self, tmp_path):
        _write_manifest(tmp_path)
        (tmp_path / "_quarto.yml").write_text(yaml.dump({
            "book": {"chapters": [{"part": "Section 1", "chapters": ["a.qmd"]}]}
        }))
        with pytest.raises(TocError, match="part:"):
            build_toc(tmp_path)


class TestWriteTocYaml:
    def test_roundtrips(self, tmp_path):
        data = {"chapters": [{"path": "x", "label": "sec-x", "title": "X", "sections": []}],
                "appendices": []}
        out_path = tmp_path / "toc.yml"
        write_toc_yaml(data, out_path)
        assert yaml.safe_load(out_path.read_text()) == data
