"""Lens markup: per-bubble data-* + lane-hit click targets (#143)."""

from __future__ import annotations
from antiquarian.render import render_swimlane

_TL = {
    "full_span": {
        "start": "2020-01-01T00:00:00+00:00",
        "end": "2026-01-01T00:00:00+00:00",
        "days": 2192,
    },
    "active_windows": [],
    "gaps": [],
}


def _commit(sha="abc123", **kw):
    base = {
        "short_sha": sha,
        "sha": sha,
        "timestamp": "2021-06-01T00:00:00+00:00",
        "date": "2021-06-01",
        "additions": 3,
        "deletions": 2,
        "subject": "s",
        "arcs": [],
        "files_changed": [],
        "detail": "did a thing",
        "detail_source": "commit",
        "pr_url": None,
        "commit_url": "https://x/commit/abc123",
    }
    base.update(kw)
    return base


def _lane(commits, author="Ada"):
    return {
        "author": author,
        "email": "a@b.c",
        "commit_count": len(commits),
        "total_loc": 5,
        "commits": commits,
    }


def test_bubble_carries_lens_data():
    out = render_swimlane({"lanes": [_lane([_commit()])]}, _TL, [])
    assert 'data-sha="abc123"' in out
    assert 'data-lane="0"' in out
    assert 'data-date="2021-06-01"' in out
    assert 'data-detail="did a thing"' in out
    assert 'data-commit-url="https://x/commit/abc123"' in out


def test_lane_hit_rect_present():
    out = render_swimlane({"lanes": [_lane([_commit()], author="Ada")]}, _TL, [])
    assert 'class="lane-hit"' in out
    assert 'data-lane="0"' in out
    assert 'data-author="Ada"' in out


def test_no_pr_url_attr_when_absent():
    out = render_swimlane({"lanes": [_lane([_commit(pr_url=None)])]}, _TL, [])
    assert "data-pr-url=" not in out
