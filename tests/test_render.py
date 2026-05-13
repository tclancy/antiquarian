"""Smoke tests for the broadsheet renderer (issue #40).

These tests own the contract that:
1. ``extract_render_data`` returns the expected top-level keys.
2. ``render_broadsheet`` produces a complete HTML document with inline SVG
   and survives empty/partial inputs.
3. The CLI command writes the expected file path.

We deliberately avoid golden-file-testing the full SVG output — the rendered
bytes will drift as the visual vocabulary evolves, and a strict golden test
would have to be regenerated on every CSS tweak. Instead, pin on structural
markers ("<svg", "broadsheet", masthead title) and the data contract.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from antiquarian.cli import app
from antiquarian.render import (
    _story_md_to_html_name,
    render_broadsheet,
    render_story_page,
)
from antiquarian.render_data import extract_render_data

runner = CliRunner()


def _seed_cache_db(repo: Path) -> None:
    """Seed a minimal .antiquarian/cache.db with two commits over two files.

    Schema matches antiquarian/cache.py — kept inline because we want the
    tests to break loudly when the schema drifts, not to silently re-create it.
    """
    db_path = repo / ".antiquarian" / "cache.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE commit_features (
            sha TEXT NOT NULL,
            file_path TEXT NOT NULL,
            id TEXT NOT NULL,
            jj_change_id TEXT,
            jj_commit_id TEXT,
            author TEXT NOT NULL,
            author_email TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            hour_of_day INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            message TEXT NOT NULL,
            files_changed TEXT NOT NULL,
            additions INTEGER NOT NULL,
            deletions INTEGER NOT NULL,
            pr_number INTEGER,
            pr_body TEXT,
            is_revert INTEGER NOT NULL DEFAULT 0,
            commit_binge_window_minutes INTEGER,
            PRIMARY KEY (sha, file_path)
        );
        """
    )
    rows = [
        (
            "aaa11111",
            "src/a.py",
            "id-a",
            None,
            None,
            "Alice",
            "alice@example.com",
            "2026-01-15T10:30:00+00:00",
            10,
            3,
            "Initial commit",
            '["src/a.py"]',
            12,
            0,
            None,
            None,
        ),
        (
            "bbb22222",
            "src/b.py",
            "id-b",
            None,
            None,
            "Bob",
            "bob@example.com",
            "2026-03-20T14:15:00+00:00",
            14,
            4,
            "Second commit",
            '["src/b.py", "src/a.py"]',
            30,
            5,
            None,
            None,
        ),
    ]
    conn.executemany(
        "INSERT INTO commit_features ("
        "sha, file_path, id, jj_change_id, jj_commit_id, author, author_email,"
        " timestamp, hour_of_day, day_of_week, message, files_changed,"
        " additions, deletions, pr_number, pr_body"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def seeded_repo(tmp_path: Path) -> Path:
    """A tmp git-like dir with a populated .antiquarian/cache.db."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "src" / "b.py").write_text("y = 2\n")
    _seed_cache_db(tmp_path)
    return tmp_path


class TestExtractRenderData:
    def test_returns_expected_top_level_keys(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        for key in (
            "project",
            "repo_path",
            "generated_at",
            "files",
            "commits",
            "todos",
            "arcs",
            "swimlane",
            "arc_band",
            "timeline",
            "file_lifespans",
            "survey_excerpt",
        ):
            assert key in data, f"missing key: {key}"

    def test_commits_loaded_from_cache(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        assert len(data["commits"]) == 2
        shas = {c["sha"] for c in data["commits"]}
        assert shas == {"aaa11111", "bbb22222"}

    def test_swimlane_groups_by_author(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        lanes = data["swimlane"]["lanes"]
        emails = {lane["email"] for lane in lanes}
        assert emails == {"alice@example.com", "bob@example.com"}

    def test_empty_cache_returns_safe_shape(self, tmp_path: Path):
        """No cache.db → all collections empty but keys still present."""
        data = extract_render_data(tmp_path)
        assert data["files"] == []
        assert data["commits"] == []
        assert data["arcs"] == []
        assert data["todos"] == []
        assert data["timeline"]["full_span"] is None
        assert data["survey_excerpt"] is None

    def test_arcs_parsed_from_stories(self, seeded_repo: Path):
        """If a story.md exists with arc paragraphs, they're parsed."""
        stories_dir = seeded_repo / ".antiquarian" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "src__a.py.md").write_text(
            "## Origin\nThe file was introduced.\n\n"
            "## Major arcs\n"
            "**Arc 1 — Initial sketch (January 2026).** A first cut at "
            "the module landed in `aaa11111`.\n\n"
            "**Arc 2 — Hardening (March 2026).** Coverage expanded in "
            "`bbb22222`.\n"
        )
        data = extract_render_data(seeded_repo)
        assert len(data["arcs"]) == 2
        names = {a["name"] for a in data["arcs"]}
        assert names == {"Initial sketch", "Hardening"}


class TestRenderBroadsheet:
    def test_produces_html_document(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        assert html.startswith("<!doctype html>")
        assert "<svg" in html
        assert "broadsheet" in html
        assert data["project"] in html

    def test_survives_empty_repo(self, tmp_path: Path):
        """Empty-cache extraction still renders a valid page — no crash."""
        data = extract_render_data(tmp_path)
        html = render_broadsheet(data)
        assert html.startswith("<!doctype html>")

    def test_survey_excerpt_xml_escaped(self, seeded_repo: Path):
        surveys_dir = seeded_repo / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True, exist_ok=True)
        (surveys_dir / "survey-test.md").write_text(
            "## Files surveyed\nintro.\n\n"
            "## Cross-file arcs\n"
            "**Arc 1 — A & B together.** They share <tags> in commits.\n"
        )
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        # Raw HTML-significant characters from the excerpt got escaped before
        # interpolation, so the page is still well-formed
        assert "&amp;" in html or "&lt;tags&gt;" in html


class TestRenderCli:
    def test_render_command_writes_file(self, seeded_repo: Path):
        result = runner.invoke(app, ["render", "--repo", str(seeded_repo)])
        assert result.exit_code == 0, result.output + result.stderr
        out_path = seeded_repo / ".antiquarian" / "render" / "index.html"
        assert out_path.exists()
        content = out_path.read_text()
        assert "<svg" in content
        assert "broadsheet" in content

    def test_render_command_errors_when_no_cache(self, tmp_path: Path):
        """No cache.db → exit 1 with a hint to run story/survey first."""
        result = runner.invoke(app, ["render", "--repo", str(tmp_path)])
        assert result.exit_code == 1
        # The hint mentions story or survey
        assert "story" in result.stderr or "survey" in result.stderr

    def test_render_command_honors_output_flag(self, seeded_repo: Path, tmp_path: Path):
        custom_out = tmp_path / "custom" / "broadsheet.html"
        result = runner.invoke(
            app,
            ["render", "--repo", str(seeded_repo), "--output", str(custom_out)],
        )
        assert result.exit_code == 0, result.output + result.stderr
        assert custom_out.exists()


class TestStoryPageRendering:
    """Issue #46 — per-file stories rendered as HTML siblings, broadsheet links into them."""

    def test_story_md_to_html_name(self):
        assert _story_md_to_html_name("src__a.py.md") == "src__a.py.html"
        # Non-.md inputs get a .html suffix appended (defensive default)
        assert _story_md_to_html_name("plain") == "plain.html"

    def test_render_story_page_produces_html(self):
        md = (
            "## Origin\n"
            "The file was introduced in `aaa11111`.\n\n"
            "## Major arcs\n"
            "**Arc 1 — Initial sketch.** A first cut at the module.\n"
        )
        html = render_story_page("src/a.py", md, "myproject")
        assert html.startswith("<!doctype html>")
        # File path appears in the title and the H1
        assert "src/a.py" in html
        assert "myproject" in html
        # Markdown converted to HTML
        assert "<h2>Origin</h2>" in html
        assert "<strong>Arc 1" in html
        assert "<code>aaa11111</code>" in html
        # Back-link to the broadsheet
        assert 'href="../index.html"' in html

    def test_render_story_page_strips_digest_marker(self):
        """The pipeline prepends a cache-digest HTML comment; render should hide it."""
        md = "<!-- antiquarian-cache-digest: abc123 -->\n## Origin\nThe story begins.\n"
        html = render_story_page("f.py", md, "proj")
        assert "antiquarian-cache-digest" not in html
        assert "<h2>Origin</h2>" in html

    def test_broadsheet_links_only_rendered_stories(self):
        """A story md filename not in stories_with_pages stays plain."""
        data = {
            "project": "p",
            "repo_path": "/tmp/p",
            "generated_at": "2026-05-13T00:00:00+00:00",
            "files": ["src/a.py", "src/b.py"],
            "stories": ["src__a.py.md", "src__b.py.md"],
            "commits": [],
            "todos": [],
            "arcs": [],
            "swimlane": {
                "lane_count": 0,
                "lanes": [],
                "time_min": None,
                "time_max": None,
            },
            "arc_band": {"arc_count": 0, "arcs": []},
            "timeline": {
                "full_span": None,
                "active_windows": [],
                "gaps": [],
                "active_total_days": 0,
                "compression_ratio": 1.0,
            },
            "file_lifespans": [],
            "survey_excerpt": None,
        }
        # Only src/a.py has a rendered HTML page
        html = render_broadsheet(data, stories_with_pages={"src__a.py.md"})
        assert 'href="stories/src__a.py.html"' in html
        assert 'href="stories/src__b.py.html"' not in html

    def test_render_cli_writes_story_pages(self, seeded_repo: Path):
        """CLI render command produces stories/*.html alongside index.html."""
        stories_dir = seeded_repo / ".antiquarian" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "src__a.py.md").write_text(
            "## Origin\nIntroduced in `aaa11111`.\n"
        )
        result = runner.invoke(app, ["render", "--repo", str(seeded_repo)])
        assert result.exit_code == 0, result.output + result.stderr

        render_dir = seeded_repo / ".antiquarian" / "render"
        index = render_dir / "index.html"
        story_page = render_dir / "stories" / "src__a.py.html"
        assert index.exists()
        assert story_page.exists()
        # Index links the story
        assert "stories/src__a.py.html" in index.read_text()
        # Story page renders the markdown body
        assert "<h2>Origin</h2>" in story_page.read_text()
