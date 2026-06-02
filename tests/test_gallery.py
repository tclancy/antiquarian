"""Tests for the gallery assembler (#92).

The assembler turns already-rendered broadsheets into a self-contained
gallery site. It makes no network or `claude -p` calls, so everything here
runs against fixtures on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from antiquarian.gallery import (
    GalleryError,
    build_gallery,
    load_manifest,
    render_gallery_index,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

_MANIFEST = """\
[gallery]
title = "The Antiquarian Gallery"
subtitle = "Illuminated histories of notable codebases"
action_url = "https://github.com/tclancy/antiquarian"

[[repos]]
slug = "requests"
name = "requests"
tagline = "HTTP for humans."
github_url = "https://github.com/psf/requests"
render_dir = "renders/requests"

[[repos]]
slug = "flask"
name = "Flask"
tagline = "A micro web framework."
github_url = "https://github.com/pallets/flask"
render_dir = "renders/flask"
"""


def _write_render(base: Path, slug: str, body: str = "broadsheet") -> None:
    """Create a minimal fake `render` output dir for *slug*."""
    render = base / "renders" / slug
    (render / "stories").mkdir(parents=True, exist_ok=True)
    (render / "index.html").write_text(
        f"<html><body>{slug} {body}</body></html>", encoding="utf-8"
    )
    (render / "stories" / "a.html").write_text("<html>story</html>", encoding="utf-8")


@pytest.fixture
def manifest_project(tmp_path: Path) -> Path:
    """A directory holding a manifest plus two fake render dirs."""
    (tmp_path / "gallery.toml").write_text(_MANIFEST, encoding="utf-8")
    _write_render(tmp_path, "requests")
    _write_render(tmp_path, "flask")
    return tmp_path


# --------------------------------------------------------------------------
# load_manifest
# --------------------------------------------------------------------------


class TestLoadManifest:
    def test_parses_valid_manifest(self, manifest_project: Path):
        manifest = load_manifest(manifest_project / "gallery.toml")
        assert manifest.title == "The Antiquarian Gallery"
        assert manifest.action_url.endswith("antiquarian")
        assert [r.slug for r in manifest.repos] == ["requests", "flask"]
        assert manifest.repos[0].tagline == "HTTP for humans."

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(GalleryError, match="not found"):
            load_manifest(tmp_path / "nope.toml")

    def test_missing_repo_field_raises(self, tmp_path: Path):
        (tmp_path / "g.toml").write_text(
            '[gallery]\ntitle = "x"\n\n[[repos]]\nslug = "a"\n',
            encoding="utf-8",
        )
        with pytest.raises(GalleryError, match="name"):
            load_manifest(tmp_path / "g.toml")

    def test_no_repos_raises(self, tmp_path: Path):
        (tmp_path / "g.toml").write_text('[gallery]\ntitle = "x"\n', encoding="utf-8")
        with pytest.raises(GalleryError, match="at least one"):
            load_manifest(tmp_path / "g.toml")

    def test_duplicate_slug_raises(self, tmp_path: Path):
        body = (
            '[gallery]\ntitle = "x"\n'
            '\n[[repos]]\nslug = "a"\nname = "A"\ntagline = "t"\n'
            'github_url = "u"\nrender_dir = "r"\n'
            '\n[[repos]]\nslug = "a"\nname = "A2"\ntagline = "t"\n'
            'github_url = "u"\nrender_dir = "r"\n'
        )
        (tmp_path / "g.toml").write_text(body, encoding="utf-8")
        with pytest.raises(GalleryError, match="duplicate"):
            load_manifest(tmp_path / "g.toml")


# --------------------------------------------------------------------------
# build_gallery
# --------------------------------------------------------------------------


class TestBuildGallery:
    def test_assembles_tree(self, manifest_project: Path, tmp_path: Path):
        out = tmp_path / "out"
        manifest = load_manifest(manifest_project / "gallery.toml")
        result = build_gallery(manifest, manifest_project, out)

        assert result == out / "index.html"
        assert (out / "index.html").exists()
        assert (out / ".nojekyll").exists()
        # each repo's render copied under its slug
        assert (out / "requests" / "index.html").exists()
        assert (out / "requests" / "stories" / "a.html").exists()
        assert (out / "flask" / "index.html").exists()

    def test_index_links_each_repo(self, manifest_project: Path, tmp_path: Path):
        out = tmp_path / "out"
        manifest = load_manifest(manifest_project / "gallery.toml")
        build_gallery(manifest, manifest_project, out)
        html = (out / "index.html").read_text(encoding="utf-8")
        assert 'href="requests/index.html"' in html
        assert 'href="flask/index.html"' in html

    def test_missing_render_dir_raises(self, tmp_path: Path):
        (tmp_path / "gallery.toml").write_text(_MANIFEST, encoding="utf-8")
        _write_render(tmp_path, "requests")  # flask render is absent
        manifest = load_manifest(tmp_path / "gallery.toml")
        with pytest.raises(GalleryError, match="flask"):
            build_gallery(manifest, tmp_path, tmp_path / "out")

    def test_rebuild_is_idempotent(self, manifest_project: Path, tmp_path: Path):
        out = tmp_path / "out"
        manifest = load_manifest(manifest_project / "gallery.toml")
        build_gallery(manifest, manifest_project, out)
        first = (out / "requests" / "index.html").read_text(encoding="utf-8")
        # second run should not duplicate or error
        build_gallery(manifest, manifest_project, out)
        assert (out / "requests" / "index.html").read_text(encoding="utf-8") == first
        assert len(list((out / "requests").glob("index.html"))) == 1


# --------------------------------------------------------------------------
# render_gallery_index
# --------------------------------------------------------------------------


class TestGalleryBuildCommand:
    """The `antiquarian gallery build` CLI wiring (#92)."""

    def test_build_command_succeeds(self, manifest_project: Path, tmp_path: Path):
        from typer.testing import CliRunner

        from antiquarian.cli import app

        out = tmp_path / "site"
        result = CliRunner().invoke(
            app,
            [
                "gallery",
                "build",
                "--manifest",
                str(manifest_project / "gallery.toml"),
                "--output",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert (out / "index.html").exists()
        assert (out / "requests" / "index.html").exists()

    def test_build_command_reports_error(self, tmp_path: Path):
        from typer.testing import CliRunner

        from antiquarian.cli import app

        result = CliRunner().invoke(
            app,
            ["gallery", "build", "--manifest", str(tmp_path / "missing.toml")],
        )
        assert result.exit_code == 1
        assert "Error" in result.stderr


class TestRenderGalleryIndex:
    def test_contains_identity_and_cta(self, manifest_project: Path):
        manifest = load_manifest(manifest_project / "gallery.toml")
        html = render_gallery_index(manifest)
        assert manifest.title in html
        assert manifest.subtitle in html
        # every repo surfaces with its tagline
        for repo in manifest.repos:
            assert repo.name in html
            assert repo.tagline in html
        # the "do it on yours" CTA points at the action
        assert manifest.action_url in html
        assert "your repo" in html.lower()

    def test_self_contained_and_styled(self, manifest_project: Path):
        manifest = load_manifest(manifest_project / "gallery.toml")
        html = render_gallery_index(manifest)
        assert "<!doctype html>" in html.lower()
        assert "EB Garamond" in html  # broadsheet face
        assert "#f4ead4" in html  # parchment paper from the broadsheet palette
        assert "<script" not in html.lower()  # no JS, Pages-safe

    def test_escapes_repo_text(self, tmp_path: Path):
        body = (
            '[gallery]\ntitle = "T"\n'
            '\n[[repos]]\nslug = "x"\nname = "a<b>"\n'
            'tagline = "t & u"\ngithub_url = "u"\nrender_dir = "r"\n'
        )
        (tmp_path / "g.toml").write_text(body, encoding="utf-8")
        manifest = load_manifest(tmp_path / "g.toml")
        html = render_gallery_index(manifest)
        assert "a<b>" not in html
        assert "a&lt;b&gt;" in html
        assert "t &amp; u" in html
