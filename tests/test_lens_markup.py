"""Lens markup: per-bubble data-* + lane-hit click targets (#143)."""

from __future__ import annotations

from antiquarian.render import render_broadsheet, render_swimlane

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


def _page():
    return render_broadsheet(
        {
            "project": "p",
            "timeline": _TL,
            "todos": [],
            "swimlane": {"lanes": [_lane([_commit()])]},
            "arc_band": {"arc_count": 0, "arcs": []},
            "file_lifespans": [],
            "files": [],
            "generated_at": "2026-06-18",
        }
    )


def test_lens_css_and_script_present():
    html = _page()
    assert ".commit-lens" in html
    assert "lane-hit" in html
    assert "commit-lens" in html  # script references the container class
    # print hides the lens
    print_block = html[html.index("@media print") :]
    assert "commit-lens" in print_block


def test_lens_script_handles_bubble_click_and_story_link():
    html = _page()
    assert "data-story-url" in html  # script references the story link attr
    assert "commit-bubble" in html


def test_lens_css_is_absolute_overlay():
    html = _page()
    # the lens overlays (absolute), and the atom is a positioning context
    assert "position: absolute" in html
    assert ".atom {" in html and "position: relative" in html
