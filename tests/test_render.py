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
    _knotwork_ribbon_svg,
    _render_dramatis_personae,
    _axis_ticks,
    _render_absolute_axis,
    _strip_empty_todo_section,
    _story_md_to_html_name,
    build_absolute_scale,
    render_broadsheet,
    render_story_page,
    render_swimlane,
    render_survey_page,
    render_todo_strip,
)
from antiquarian.render_data import (
    _build_swimlane,
    _Commit,
    _extract_story_descriptions,
    _pull_dramatis_personae,
    extract_render_data,
)

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
            "dramatis_personae",
            "story_descriptions",
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

    def test_arc_band_includes_datable_count(self, seeded_repo):
        data = extract_render_data(seeded_repo)
        for arc in data["arc_band"]["arcs"]:
            assert "datable_count" in arc
            assert arc["datable_count"] == sum(
                1 for c in arc["commits"] if c["timestamp"]
            )


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

    def test_masthead_subtitle_drops_implementation_vocabulary(self, seeded_repo: Path):
        """The masthead stays in the historian's voice — no renderer internals (#110).

        "Three atoms, hand-set in pure SVG" leaked the internal component name
        and the rendering tech into reader-facing copy.
        """
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        sub = html.split('class="masthead-sub">', 1)[1].split("</p>", 1)[0]
        assert "atom" not in sub.lower()
        assert "svg" not in sub.lower()
        # but the true-to-thesis framing stays
        assert "lossy regions" in sub
        assert "marginalia" in sub

    def test_base_font_scaled_up(self, seeded_repo: Path):
        """A single :root type-scale knob bumps all rem-based text 120% (#111)."""
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        assert "font-size: 120%" in html


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


class TestStoryDescriptions:
    """Story descriptions extracted from Origin sections appear in meta-table."""

    def test_extract_story_descriptions_basic(self, tmp_path: Path):
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        (stories_dir / "src__a.py.md").write_text(
            "## Origin\nThe module handles authentication. More details.\n"
        )
        descs = _extract_story_descriptions(list(stories_dir.glob("*.md")))
        assert descs == {"src/a.py": "The module handles authentication."}

    def test_extract_story_descriptions_strips_backtick_code(self, tmp_path: Path):
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        (stories_dir / "src__a.py.md").write_text(
            "## Origin\nIntroduced in `aaa11111` as a helper. More.\n"
        )
        descs = _extract_story_descriptions(list(stories_dir.glob("*.md")))
        assert "`" not in descs["src/a.py"]
        assert "Introduced in" in descs["src/a.py"]

    def test_extract_story_descriptions_truncates_long(self, tmp_path: Path):
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        long_sentence = "A" * 200 + "."
        (stories_dir / "src__a.py.md").write_text(f"## Origin\n{long_sentence} More.\n")
        descs = _extract_story_descriptions(list(stories_dir.glob("*.md")))
        assert len(descs["src/a.py"]) <= 120
        assert descs["src/a.py"].endswith("…")

    def test_extract_story_descriptions_no_origin_section(self, tmp_path: Path):
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        (stories_dir / "src__a.py.md").write_text("## Major arcs\nSome arcs.\n")
        descs = _extract_story_descriptions(list(stories_dir.glob("*.md")))
        assert descs == {}

    def test_broadsheet_no_stories_on_file_row(self, seeded_repo: Path):
        """The 'stories on file' row is gone from the meta-table."""
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        assert "stories on file" not in html
        assert "files surveyed" in html

    def test_broadsheet_shows_description(self, seeded_repo: Path):
        stories_dir = seeded_repo / ".antiquarian" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "src__a.py.md").write_text(
            "## Origin\nThe auth module handles login. More detail.\n"
        )
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data, stories_with_pages={"src__a.py.md"})
        assert "file-desc" in html
        assert "The auth module handles login." in html

    def test_broadsheet_no_description_no_span(self, seeded_repo: Path):
        """Files without stories don't get a description span in the body."""
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        assert '<span class="file-desc">' not in html

    def test_story_descriptions_in_extract_render_data(self, seeded_repo: Path):
        stories_dir = seeded_repo / ".antiquarian" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "src__a.py.md").write_text(
            "## Origin\nA utility module. More.\n"
        )
        data = extract_render_data(seeded_repo)
        assert "story_descriptions" in data
        assert data["story_descriptions"]["src/a.py"] == "A utility module."


class TestEmptyTodoSections:
    """No-TODO surfaces should be quiet, not loudly empty."""

    def test_render_todo_strip_empty_returns_empty_string(self):
        """No TODOs → no atom output. The broadsheet layout drops the slot."""
        timeline = {"full_span": None, "active_windows": [], "gaps": []}
        assert render_todo_strip([], timeline) == ""

    def test_render_todo_strip_at_floor_returns_svg_chart(self):
        """At/above the density floor, real data produces the bar-chart SVG."""
        timeline = {
            "full_span": {
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-06-01T00:00:00+00:00",
                "days": 152,
            },
            "active_windows": [
                {
                    "start": "2026-01-01T00:00:00+00:00",
                    "end": "2026-06-01T00:00:00+00:00",
                    "commit_count": 5,
                }
            ],
            "gaps": [],
            "active_total_days": 152,
            "compression_ratio": 1.0,
        }
        todos = [
            {
                "file_path": "src/a.py",
                "kind": "TODO",
                "line_number": 10 + i,
                "text": f"fix this {i}",
                "introduced_sha": "abc11111",
                "introduced_short": "abc11111",
                "introduced_at": "2026-01-15T10:30:00+00:00",
                "introduced_by": "Alice",
                "age_days": 100 + i,
            }
            for i in range(3)
        ]
        out = render_todo_strip(todos, timeline)
        assert out.startswith("<svg")
        assert "margins" in out.lower()

    def test_broadsheet_skips_empty_todo_chapter_mark(self, seeded_repo: Path):
        """No TODOs in the codebase → no 'i' chapter mark for the empty atom.

        The remaining atoms renumber: swimlane becomes 'i', arc_roster 'ii'.
        """
        data = extract_render_data(seeded_repo)
        # Seeded repo has no TODOs (no live HEAD files with TODO comments)
        assert data["todos"] == []
        html = render_broadsheet(data)
        # The HTML still has chapter marks for the present atoms
        assert 'class="chapter-mark">i</div>' in html
        # But only as many as there are non-empty atoms
        chapter_count = html.count('class="chapter-mark"')
        assert chapter_count == 2  # swimlane + arc_band, not 3

    def test_strip_empty_todo_section_removes_canonical_placeholder(self):
        md = (
            "## Origin\nThe file appeared.\n\n"
            "## Major arcs\n**Arc 1 — Setup.** The setup happened.\n\n"
            "## TODO/FIXME aging\n"
            "The file currently carries no TODO/FIXME admissions. "
            "That itself is a signal of the maintainers' standards.\n\n"
            "## People & ownership\nAlice owns this.\n"
        )
        out = _strip_empty_todo_section(md)
        assert "TODO/FIXME aging" not in out
        assert "currently carries no" not in out
        # Surrounding sections survive intact
        assert "## Origin" in out
        assert "## Major arcs" in out
        assert "## People & ownership" in out

    def test_strip_keeps_real_todo_content(self):
        """Real annotations should NOT be stripped."""
        md = (
            "## TODO/FIXME aging\n"
            "- **TODO** at line 42 (730d old) — introduced by Bob in commit "
            "abc11111: refactor this hack\n"
        )
        out = _strip_empty_todo_section(md)
        assert "TODO/FIXME aging" in out
        assert "refactor this hack" in out

    def test_strip_keeps_skip_and_stub_unrecoverable(self):
        """The #34 skip-and-stub uses 'Unrecoverable in this session.' which
        is also a valid no-data state. Don't strip it."""
        md = (
            "## TODO/FIXME aging\n"
            "Unrecoverable in this session.\n\n"
            "## People & ownership\n"
            "Unrecoverable in this session.\n"
        )
        out = _strip_empty_todo_section(md)
        assert "TODO/FIXME aging" in out
        assert "Unrecoverable" in out

    def test_render_story_page_strips_empty_todo_from_cached_story(self):
        md = (
            "## Origin\nThe file appeared.\n\n"
            "## TODO/FIXME aging\n"
            "The file currently carries no TODO/FIXME admissions. "
            "That itself is a signal of the maintainers' standards.\n\n"
            "## People & ownership\nAlice owns it.\n"
        )
        html = render_story_page("f.py", md, "proj")
        assert "TODO/FIXME aging" not in html
        assert "currently carries no" not in html
        # Surrounding sections still rendered
        assert "<h2>Origin</h2>" in html
        assert "<h2>People &amp; ownership</h2>" in html


class TestSurveyPageRendering:
    """Issue #81 — survey content rendered as HTML in published docs."""

    def test_render_survey_page_produces_html(self):
        md = (
            "## Files surveyed\nTwo files were analyzed.\n\n"
            "## Cross-file arcs\n"
            "**Arc 1 — Shared foundation.** Both files share a common origin.\n"
        )
        html = render_survey_page(md, "myproject", 2)
        assert html.startswith("<!doctype html>")
        assert "myproject" in html
        assert "Codebase Survey" in html
        assert "<h2>Files surveyed</h2>" in html
        assert "<strong>Arc 1" in html
        assert 'href="index.html"' in html
        assert "2 per-file stories" in html

    def test_render_survey_page_escapes_project_name(self):
        html = render_survey_page("## Intro\nHello.\n", "A <B> & C", 1)
        assert "A &lt;B&gt; &amp; C" in html

    def test_broadsheet_meta_table_links_survey_when_present(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data, has_survey=True)
        assert 'href="survey.html"' in html
        assert "full narrative synthesis" in html

    def test_broadsheet_meta_table_no_survey_link_by_default(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        assert "survey.html" not in html

    def test_broadsheet_survey_excerpt_links_to_survey(self, seeded_repo: Path):
        surveys_dir = seeded_repo / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True, exist_ok=True)
        (surveys_dir / "survey-test.md").write_text(
            "## Files surveyed\nintro.\n\n"
            "## Cross-file arcs\n"
            "**Arc 1 — Testing.** Shared patterns.\n"
        )
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data, has_survey=True)
        assert "read the full survey" in html
        assert 'href="survey.html"' in html

    def test_broadsheet_survey_link_without_excerpt(self):
        data = {
            "project": "p",
            "repo_path": "/tmp/p",
            "generated_at": "2026-05-14T00:00:00+00:00",
            "files": [],
            "stories": [],
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
        html = render_broadsheet(data, has_survey=True)
        assert "read the full codebase survey" in html
        assert 'href="survey.html"' in html

    def test_render_cli_writes_survey_page(self, seeded_repo: Path):
        surveys_dir = seeded_repo / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True, exist_ok=True)
        (surveys_dir / "survey-abc123.md").write_text(
            "## Files surveyed\nTwo files.\n\n"
            "## Cross-file arcs\n"
            "**Arc 1 — Shared.** Common origin.\n"
        )
        result = runner.invoke(app, ["render", "--repo", str(seeded_repo)])
        assert result.exit_code == 0, result.output + result.stderr

        render_dir = seeded_repo / ".antiquarian" / "render"
        survey_page = render_dir / "survey.html"
        assert survey_page.exists()
        content = survey_page.read_text()
        assert "Codebase Survey" in content
        assert "<h2>Files surveyed</h2>" in content

        index = render_dir / "index.html"
        assert 'href="survey.html"' in index.read_text()


class TestDramatisPersonae:
    """Tests for Dramatis Personae extraction and rendering."""

    SURVEY_WITH_DP = (
        "## Files surveyed\nTwo files.\n\n"
        "## Cross-file arcs\n"
        "**Arc 1 — Shared.** Common origin.\n\n"
        "## Dramatis Personae\n\n"
        "**`Tom Clancy`** — The lone maintainer who carried the project through.\n\n"
        "**`dispatch-bot[bot]`** — The scaffolder who laid down the pipeline.\n"
    )

    def test_pull_extracts_entries(self, tmp_path: Path):
        surveys_dir = tmp_path / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True)
        (surveys_dir / "survey-test.md").write_text(self.SURVEY_WITH_DP)
        entries = _pull_dramatis_personae(tmp_path)
        assert len(entries) == 2
        assert entries[0]["name"] == "Tom Clancy"
        assert "lone maintainer" in entries[0]["description"]
        assert entries[1]["name"] == "dispatch-bot[bot]"

    def test_pull_returns_empty_when_no_section(self, tmp_path: Path):
        surveys_dir = tmp_path / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True)
        (surveys_dir / "survey-test.md").write_text(
            "## Files surveyed\nOne.\n\n## Cross-file arcs\nNone.\n"
        )
        assert _pull_dramatis_personae(tmp_path) == []

    def test_pull_returns_empty_when_no_surveys_dir(self, tmp_path: Path):
        assert _pull_dramatis_personae(tmp_path) == []

    def test_pull_returns_empty_when_no_survey_files(self, tmp_path: Path):
        (tmp_path / ".antiquarian" / "surveys").mkdir(parents=True)
        assert _pull_dramatis_personae(tmp_path) == []

    def test_pull_truncates_long_descriptions(self, tmp_path: Path):
        surveys_dir = tmp_path / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True)
        long_desc = "A " * 200
        (surveys_dir / "survey-test.md").write_text(
            f"## Dramatis Personae\n\n**`Alice`** — {long_desc}\n"
        )
        entries = _pull_dramatis_personae(tmp_path)
        assert len(entries) == 1
        assert len(entries[0]["description"]) <= 300

    def test_pull_handles_names_without_backticks(self, tmp_path: Path):
        surveys_dir = tmp_path / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True)
        (surveys_dir / "survey-test.md").write_text(
            "## Dramatis Personae\n\n**Alice Smith** — Built the core module.\n"
        )
        entries = _pull_dramatis_personae(tmp_path)
        assert len(entries) == 1
        assert entries[0]["name"] == "Alice Smith"

    def test_render_produces_section_html(self):
        entries = [
            {"name": "Tom", "description": "The maintainer."},
            {"name": "Bot", "description": "The scaffolder."},
        ]
        html = _render_dramatis_personae(entries)
        assert 'class="dramatis"' in html
        assert "Dramatis Person" in html
        assert 'class="dramatis-name"' in html
        assert "Tom" in html
        assert "Bot" in html

    def test_render_returns_empty_for_no_entries(self):
        assert _render_dramatis_personae([]) == ""

    def test_render_escapes_html_in_names(self):
        entries = [{"name": "A <B> & C", "description": "Test."}]
        html = _render_dramatis_personae(entries)
        assert "&lt;B&gt;" in html
        assert "&amp;" in html

    def test_knotwork_ribbon_produces_svg(self):
        svg = _knotwork_ribbon_svg()
        assert "<svg" in svg
        assert "</svg>" in svg
        assert "path" in svg
        assert 'width="100%"' in svg

    def test_knotwork_ribbon_custom_width(self):
        svg = _knotwork_ribbon_svg(width=240)
        assert "0 0 240 18" in svg

    def test_broadsheet_includes_dramatis_when_present(self, seeded_repo: Path):
        surveys_dir = seeded_repo / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True, exist_ok=True)
        (surveys_dir / "survey-test.md").write_text(self.SURVEY_WITH_DP)
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        assert 'class="dramatis"' in html
        assert "Tom Clancy" in html
        assert "dispatch-bot" in html

    def test_broadsheet_omits_dramatis_when_absent(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        assert 'class="dramatis"' not in html

    def test_dramatis_appears_before_lede(self, seeded_repo: Path):
        surveys_dir = seeded_repo / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True, exist_ok=True)
        (surveys_dir / "survey-test.md").write_text(self.SURVEY_WITH_DP)
        data = extract_render_data(seeded_repo)
        html = render_broadsheet(data)
        dramatis_pos = html.index('class="dramatis"')
        lede_pos = html.index('class="lede"')
        assert dramatis_pos < lede_pos

    def test_extract_render_data_includes_dramatis(self, seeded_repo: Path):
        surveys_dir = seeded_repo / ".antiquarian" / "surveys"
        surveys_dir.mkdir(parents=True, exist_ok=True)
        (surveys_dir / "survey-test.md").write_text(self.SURVEY_WITH_DP)
        data = extract_render_data(seeded_repo)
        assert "dramatis_personae" in data
        assert len(data["dramatis_personae"]) == 2


class TestBuildAbsoluteScale:
    """The shared absolute time spine (#117).

    Unlike ``build_active_scale`` (which collapses dormant gaps to fixed
    pixel widths), the absolute scale maps datetimes linearly across the
    full project lifespan, so x-position means the same date in every
    atom that registers to it. Dormancy is shown at its true width.
    """

    def _span(self, start: str, end: str) -> dict:
        from datetime import datetime

        days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1
        return {
            "full_span": {"start": start, "end": end, "days": days},
            "active_windows": [],
            "gaps": [],
        }

    def test_maps_full_span_endpoints_to_pixel_bounds(self):
        from datetime import datetime

        timeline = self._span("2019-01-01T00:00:00", "2019-01-11T00:00:00")
        axis = build_absolute_scale(timeline, 100)
        assert axis["scale"](datetime.fromisoformat("2019-01-01T00:00:00")) == 0
        assert axis["scale"](datetime.fromisoformat("2019-01-11T00:00:00")) == 100

    def test_maps_midpoint_linearly(self):
        from datetime import datetime

        timeline = self._span("2019-01-01T00:00:00", "2019-01-11T00:00:00")
        axis = build_absolute_scale(timeline, 100)
        # Six days into a ten-day span is 0.6 of the way across.
        assert axis["scale"](datetime.fromisoformat("2019-01-07T00:00:00")) == 60

    def test_clamps_dates_outside_the_span(self):
        from datetime import datetime

        timeline = self._span("2019-01-01T00:00:00", "2019-01-11T00:00:00")
        axis = build_absolute_scale(timeline, 100)
        assert axis["scale"](datetime.fromisoformat("2018-01-01T00:00:00")) == 0
        assert axis["scale"](datetime.fromisoformat("2020-01-01T00:00:00")) == 100

    def test_empty_timeline_scale_returns_zero(self):
        from datetime import datetime

        axis = build_absolute_scale({"full_span": None}, 100)
        assert axis["scale"](datetime.fromisoformat("2019-01-01T00:00:00")) == 0


class TestAxisTicks:
    """Axis ticks adapt their granularity to the span (#117).

    A multi-year project gets year ticks (thinned past eight years); a project
    under ~2 years gets month ticks, because year boundaries are too coarse for
    a young repo (a sub-year one would get none). Returns ``(datetime, label)``
    pairs, the label already formatted for the chosen granularity.
    """

    def test_year_ticks_for_multiyear_span(self):
        from datetime import datetime, timezone

        start = datetime(2019, 4, 15, tzinfo=timezone.utc)
        end = datetime(2026, 2, 10, tzinfo=timezone.utc)
        ticks = _axis_ticks(start, end)
        # Jan-1-2019 precedes the April start, so it's excluded.
        assert [d.year for d, _ in ticks] == [2020, 2021, 2022, 2023, 2024, 2025, 2026]
        assert [label for _, label in ticks] == [
            "2020",
            "2021",
            "2022",
            "2023",
            "2024",
            "2025",
            "2026",
        ]

    def test_thins_to_every_other_year_for_long_span(self):
        from datetime import datetime, timezone

        start = datetime(2010, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, tzinfo=timezone.utc)
        years = [d.year for d, _ in _axis_ticks(start, end)]
        assert years == [2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026]

    def test_month_ticks_for_subyear_span(self):
        from datetime import datetime, timezone

        start = datetime(2025, 1, 15, tzinfo=timezone.utc)
        end = datetime(2025, 8, 20, tzinfo=timezone.utc)
        ticks = _axis_ticks(start, end)
        # Single-year sub-2-year span → bare month abbreviations, on the 1st.
        assert [label for _, label in ticks] == [
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
        ]
        assert all(d.day == 1 for d, _ in ticks)

    def test_month_ticks_cross_year_carry_year_suffix(self):
        from datetime import datetime, timezone

        start = datetime(2024, 11, 5, tzinfo=timezone.utc)
        end = datetime(2025, 3, 10, tzinfo=timezone.utc)
        labels = [label for _, label in _axis_ticks(start, end)]
        assert labels == ["Dec '24", "Jan '25", "Feb '25", "Mar '25"]

    def test_returns_tz_aware_dates(self):
        from datetime import datetime, timezone

        start = datetime(2021, 6, 1, tzinfo=timezone.utc)
        end = datetime(2023, 6, 1, tzinfo=timezone.utc)
        assert all(d.tzinfo is not None for d, _ in _axis_ticks(start, end))


class TestSwimlaneRegistersToAbsoluteSpine:
    """The swimlane renders on the shared absolute spine (#117).

    Year ticks span the whole project lifespan (not per-active-window date
    labels), dormant stretches are lossy-hatched at their true width, and a
    late-dated commit lands in the right-hand portion of the chart.
    """

    def _timeline(self) -> dict:
        return {
            "full_span": {
                "start": "2019-01-01T00:00:00+00:00",
                "end": "2026-12-31T00:00:00+00:00",
                "days": 2922,
            },
            "active_windows": [
                {
                    "start": "2019-01-01T00:00:00+00:00",
                    "end": "2020-06-01T00:00:00+00:00",
                    "commit_count": 1,
                },
                {
                    "start": "2023-06-01T00:00:00+00:00",
                    "end": "2026-12-31T00:00:00+00:00",
                    "commit_count": 1,
                },
            ],
            "gaps": [
                {
                    "start": "2020-06-01T00:00:00+00:00",
                    "end": "2023-06-01T00:00:00+00:00",
                    "days": 1096,
                }
            ],
        }

    def _swimlane(self) -> dict:
        def commit(ts: str) -> dict:
            return {
                "timestamp": ts,
                "additions": 10,
                "deletions": 0,
                "arcs": [],
                "short_sha": "abc1234",
                "subject": "a commit",
            }

        return {
            "lanes": [
                {
                    "author": "Ada",
                    "commit_count": 2,
                    "commits": [
                        commit("2019-03-01T00:00:00+00:00"),
                        commit("2025-11-01T00:00:00+00:00"),
                    ],
                }
            ]
        }

    def test_renders_dormancy_hatch_for_the_gap(self):
        out = render_swimlane(self._swimlane(), self._timeline(), [])
        assert "url(#lossy-hatch)" in out

    def test_axis_labels_span_the_full_lifespan(self):
        out = render_swimlane(self._swimlane(), self._timeline(), [])
        # Absolute axis labels every (in-range) year, not per-window ranges.
        assert ">2020</text>" in out
        assert ">2026</text>" in out

    def test_late_commit_lands_in_right_portion(self):
        import re

        out = render_swimlane(self._swimlane(), self._timeline(), [])
        # margin_left=220, chart_w=760 → absolute midpoint x ≈ 600.
        # A 2025 commit in a 2019–2026 span sits well past the midpoint.
        cxs = sorted(float(m) for m in re.findall(r'<circle cx="([\d.]+)"', out))
        assert cxs[-1] > 700


class TestAbsoluteAxisAnchorsSpanEnds:
    """The absolute axis is never blank — even a sub-year span is labelled (#117).

    Year ticks alone vanish for a project that lives inside one calendar year
    (Jan 1 falls before the start), so the axis always anchors the span's
    first and last dates.
    """

    def test_subyear_span_still_labels_the_endpoints(self):
        timeline = {
            "full_span": {
                "start": "2026-05-01T00:00:00+00:00",
                "end": "2026-06-15T00:00:00+00:00",
                "days": 46,
            },
            "active_windows": [],
            "gaps": [],
        }
        out = _render_absolute_axis(timeline, 100, 600, 50)
        assert "May 2026" in out
        assert "Jun 2026" in out

    def test_multiyear_span_keeps_interior_year_ticks(self):
        timeline = {
            "full_span": {
                "start": "2019-04-01T00:00:00+00:00",
                "end": "2026-02-01T00:00:00+00:00",
                "days": 2498,
            },
            "active_windows": [],
            "gaps": [],
        }
        out = _render_absolute_axis(timeline, 100, 600, 50)
        assert ">2022</text>" in out


def _commit(
    email: str, ts: str, *, add: int = 1, dele: int = 0, author: str = "X"
) -> _Commit:
    return _Commit(
        sha=ts,
        short_sha=ts[:8],
        author=author,
        author_email=email,
        timestamp=ts,
        date=ts[:10],
        message_subject="m",
        additions=add,
        deletions=dele,
        files_changed_count=1,
        pr_number=None,
    )


class TestSwimlaneRanking:
    """Lanes rank by contribution so the eye can compare (#118).

    The flat chronological order made it impossible to tell who did the most;
    lanes now sort by commit count descending, with total LoC as the tiebreak.
    """

    def test_lanes_sorted_by_commit_count_desc(self):
        commits = [
            _commit("a@x", "2026-01-01T00:00:00+00:00"),
            _commit("a@x", "2026-01-02T00:00:00+00:00"),
            _commit("a@x", "2026-01-03T00:00:00+00:00"),
            _commit("b@x", "2026-01-04T00:00:00+00:00"),
            _commit("c@x", "2026-01-05T00:00:00+00:00"),
            _commit("c@x", "2026-01-06T00:00:00+00:00"),
        ]
        lanes = _build_swimlane(commits)["lanes"]
        assert [lane["email"] for lane in lanes] == ["a@x", "c@x", "b@x"]

    def test_ties_broken_by_total_loc_desc(self):
        commits = [
            _commit("low@x", "2026-01-01T00:00:00+00:00", add=1, dele=0),
            _commit("high@x", "2026-01-02T00:00:00+00:00", add=50, dele=10),
        ]
        lanes = _build_swimlane(commits)["lanes"]
        assert [lane["email"] for lane in lanes] == ["high@x", "low@x"]


class TestSwimlaneLongTailCollapse:
    """Beyond a budget, lanes fold into a searchable HTML tail (#118).

    The top contributors render as SVG lanes; the rest go into a
    ``<details>`` list (name + count) that stays in the DOM — Ctrl-F-able and
    print-expanded — so no name is ever silently dropped.
    """

    def _timeline(self) -> dict:
        return {
            "full_span": {
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-06-01T00:00:00+00:00",
                "days": 151,
            },
            "active_windows": [],
            "gaps": [],
        }

    def _lanes(self, n: int) -> dict:
        lanes = []
        for i in range(n):
            lanes.append(
                {
                    "author": f"Person {i}",
                    "email": f"p{i}@x",
                    "commit_count": n - i,
                    "total_loc": (n - i) * 10,
                    "first_commit": "2026-02-01T00:00:00+00:00",
                    "last_commit": "2026-05-01T00:00:00+00:00",
                    "commits": [
                        {
                            "timestamp": "2026-03-01T00:00:00+00:00",
                            "additions": 5,
                            "deletions": 1,
                            "arcs": [],
                            "short_sha": "abc1234",
                            "subject": "s",
                        }
                    ],
                }
            )
        return {"lanes": lanes}

    def test_tail_folds_below_budget_but_keeps_names(self):
        out = render_swimlane(self._lanes(5), self._timeline(), [], lane_budget=3)
        # Top 3 render as SVG lanes; the other 2 live in a details tail.
        assert "<details" in out
        assert "Person 3" in out  # a tail name is still present (searchable)
        assert "Person 4" in out
        # Every contributor name appears somewhere in the output.
        for i in range(5):
            assert f"Person {i}" in out

    def test_tail_summary_counts_the_hidden_hands(self):
        out = render_swimlane(self._lanes(5), self._timeline(), [], lane_budget=3)
        assert "2 more" in out  # +2 hands folded

    def test_no_tail_when_within_budget(self):
        out = render_swimlane(self._lanes(3), self._timeline(), [], lane_budget=3)
        assert "<details" not in out


class TestMailmapCoalescing:
    """A repo .mailmap collapses an author's multiple emails into one lane (#118)."""

    def test_mailmap_coalesces_swimlane_lanes(self, seeded_repo: Path):
        # Declare Bob's address an alias of Alice's.
        (seeded_repo / ".mailmap").write_text(
            "Alice <alice@example.com> <bob@example.com>\n"
        )
        data = extract_render_data(seeded_repo)
        lanes = data["swimlane"]["lanes"]
        assert len(lanes) == 1
        assert lanes[0]["email"] == "alice@example.com"
        assert lanes[0]["commit_count"] == 2

    def test_no_mailmap_leaves_lanes_separate(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        assert len(data["swimlane"]["lanes"]) == 2
