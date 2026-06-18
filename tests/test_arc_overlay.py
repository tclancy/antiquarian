"""Tests for the arc overlay on the swimlane (#119, PR-B).

Decisive commits link to their story page and name their arc on hover; bubbles
carry their arc slugs so the hover highlight (next task) can light real co-arc
commits. Honest: marks only, never a band.
"""

from __future__ import annotations

from antiquarian.render import render_swimlane

_TIMELINE = {
    "full_span": {
        "start": "2020-01-01T00:00:00+00:00",
        "end": "2026-01-01T00:00:00+00:00",
        "days": 2192,
    },
    "active_windows": [],
    "gaps": [],
}


def _lane(commits):
    return {
        "author": "Ada",
        "commit_count": len(commits),
        "total_loc": 9,
        "email": "a@b.c",
        "commits": commits,
    }


def _commit(
    sha, arcs, *, ts="2021-06-01T00:00:00+00:00", add=3, dele=2, subj="do a thing"
):
    return {
        "short_sha": sha,
        "timestamp": ts,
        "additions": add,
        "deletions": dele,
        "subject": subj,
        "arcs": arcs,
    }


def test_bubble_has_class_and_data_arcs():
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, []
    )
    assert 'class="commit-bubble"' in out
    assert 'data-arcs="transport-api"' in out


def test_non_decisive_bubble_has_empty_data_arcs():
    out = render_swimlane({"lanes": [_lane([_commit("abc123", [])])]}, _TIMELINE, [])
    assert 'data-arcs=""' in out


def test_decisive_bubble_names_arc_in_tooltip_when_lookup_given():
    lookup = {"transport-api": {"name": "Transport API rework", "story_href": None}}
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]},
        _TIMELINE,
        [],
        arc_lookup=lookup,
    )
    assert "Transport API rework" in out


def test_decisive_bubble_links_to_story_when_page_exists():
    lookup = {
        "transport-api": {
            "name": "Transport API rework",
            "story_href": "stories/httpx___client.py.html",
        }
    }
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]},
        _TIMELINE,
        [],
        arc_lookup=lookup,
    )
    assert '<a href="stories/httpx___client.py.html">' in out
    assert "</a>" in out


def test_no_lookup_keeps_data_arcs_but_no_link():
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, []
    )
    assert 'data-arcs="transport-api"' in out
    assert "<a href=" not in out  # no lookup → no story link
