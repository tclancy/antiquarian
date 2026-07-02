"""Tests for commit detail enrichment feeding the commit lens (#143)."""

from __future__ import annotations

from pathlib import Path

from antiquarian.link_backend import GitHubBackend, NoopLinkBackend
from antiquarian.render_data import (
    _build_swimlane,
    _Commit,
    _truncate_words,
    extract_render_data,
)


def _commit(**kw) -> _Commit:
    base = dict(
        sha="7af3c1b1234567",
        short_sha="7af3c1b",
        author="dev",
        author_email="dev@e.com",
        timestamp="2021-05-11T00:00:00+00:00",
        date="2021-05-11",
        message_subject="do a thing",
        additions=1,
        deletions=0,
        files_changed_count=1,
    )
    base.update(kw)
    return _Commit(**base)


def test_swimlane_detail_linkifies_hash_and_sha_refs():
    """The popover detail is linkified like story prose (#113)."""
    c = _commit(pr_body="Related to httpcore. Refs #503 and 7af3c1b.")
    lane = _build_swimlane([c], "https://github.com/o/r", GitHubBackend("o", "r"))
    detail = lane["lanes"][0]["commits"][0]["detail"]
    assert "[#503](https://github.com/o/r/issues/503)" in detail
    assert "[`7af3c1b`](https://github.com/o/r/commit/7af3c1b)" in detail


def test_swimlane_detail_noop_backend_leaves_refs_plain():
    c = _commit(pr_body="Refs #503.")
    lane = _build_swimlane([c], None, NoopLinkBackend())
    assert lane["lanes"][0]["commits"][0]["detail"] == "Refs #503."


def test_swimlane_detail_defaults_to_noop_when_backend_omitted():
    c = _commit(pr_body="Refs #503.")
    lane = _build_swimlane([c])
    assert "#503" in lane["lanes"][0]["commits"][0]["detail"]
    assert "issues/503" not in lane["lanes"][0]["commits"][0]["detail"]


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
