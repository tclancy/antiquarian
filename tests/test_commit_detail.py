"""Tests for commit detail enrichment feeding the commit lens (#143)."""

from __future__ import annotations

from pathlib import Path

from antiquarian.render_data import _truncate_words, extract_render_data


def test_truncate_short_text_unchanged():
    assert _truncate_words("a b c", 5) == "a b c"


def test_truncate_long_text_adds_ellipsis():
    out = _truncate_words("one two three four five six", 3)
    assert out == "one two three…"


def test_truncate_collapses_whitespace():
    assert _truncate_words("  a\n\n  b   c ", 10) == "a b c"


def test_truncate_empty():
    assert _truncate_words("", 5) == "" and _truncate_words(None, 5) == ""


def test_swimlane_commits_carry_detail_fields(seeded_repo: Path):
    data = extract_render_data(seeded_repo)
    commits = [c for lane in data["swimlane"]["lanes"] for c in lane["commits"]]
    assert commits, "fixture should have commits"
    for c in commits:
        assert "detail" in c and "detail_source" in c
        assert c["detail_source"] in ("pr", "commit")
        assert "pr_url" in c and "commit_url" in c
