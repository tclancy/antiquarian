"""Tests for the pure arc lane-packing module (#112).

pack_arcs places every datable arc onto the fewest horizontal rows such that
no two lozenges overlap within a row — a greedy interval packing, proven here
independently of any SVG. The spine is injected as a plain callable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from antiquarian.arc_layout import (
    LANE_GAP_PX,
    MIN_LOZENGE_PX,
    PlacedArc,
    pack_arcs,
)

BASE = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _scale(dt: datetime) -> float:
    """Days-since-BASE as the pixel coordinate — a simple injectable spine."""
    return (dt - BASE).total_seconds() / 86400.0


def _arc(
    number: int, start_day: float, end_day: float, *, extra_commits: int = 0
) -> dict:
    """An arc whose datable commits span [start_day, end_day]."""
    commits = [
        {"timestamp": (BASE + timedelta(days=start_day)).isoformat(), "short_sha": "a"},
        {"timestamp": (BASE + timedelta(days=end_day)).isoformat(), "short_sha": "b"},
    ]
    commits += [{"timestamp": None, "short_sha": "x"} for _ in range(extra_commits)]
    return {
        "arc_number": number,
        "name": f"Arc {number}",
        "file_path": "a.py",
        "commits": commits,
    }


def _no_overlap_within_rows(rows: list[list[PlacedArc]], gap: float) -> bool:
    for row in rows:
        ordered = sorted(row, key=lambda p: p.x_start)
        for prev, cur in zip(ordered, ordered[1:]):
            if cur.x_start < prev.x_end + gap:
                return False
    return True


def test_empty_arcs_yields_no_rows():
    assert pack_arcs([], _scale) == []


def test_single_arc_one_row():
    rows = pack_arcs([_arc(1, 0, 10)], _scale)
    assert len(rows) == 1
    assert len(rows[0]) == 1
    assert rows[0][0].x_start == 0.0
    assert rows[0][0].x_end == 10.0


def test_overlapping_arcs_get_separate_rows():
    rows = pack_arcs([_arc(1, 0, 10), _arc(2, 5, 15)], _scale)
    assert len(rows) == 2


def test_disjoint_arcs_share_a_row():
    # second arc starts well after the first ends (> gap)
    rows = pack_arcs([_arc(1, 0, 10), _arc(2, 40, 50)], _scale)
    assert len(rows) == 1
    assert len(rows[0]) == 2


def test_every_datable_arc_placed_exactly_once():
    arcs = [_arc(i, i * 2, i * 2 + 1) for i in range(20)] + [_arc(99, 0, 100)]
    rows = pack_arcs(arcs, _scale)
    placed = [p.arc["arc_number"] for row in rows for p in row]
    assert sorted(placed) == sorted(a["arc_number"] for a in arcs)
    assert len(placed) == len(set(placed))  # exactly once


def test_no_overlap_within_any_row():
    arcs = [_arc(i, i, i + 5) for i in range(30)]
    rows = pack_arcs(arcs, _scale)
    assert _no_overlap_within_rows(rows, LANE_GAP_PX)


def test_non_datable_arcs_are_excluded():
    nodate = {
        "arc_number": 7,
        "name": "Arc 7",
        "file_path": "a.py",
        "commits": [{"timestamp": None, "short_sha": "x"}],
    }
    rows = pack_arcs([_arc(1, 0, 10), nodate], _scale)
    placed = [p.arc["arc_number"] for row in rows for p in row]
    assert placed == [1]


def test_single_commit_arc_gets_min_width():
    rows = pack_arcs([_arc(1, 5, 5)], _scale)  # zero-span
    pa = rows[0][0]
    assert pa.x_end - pa.x_start == MIN_LOZENGE_PX


def test_deterministic_and_sorted_by_start():
    arcs = [_arc(3, 30, 31), _arc(1, 0, 1), _arc(2, 60, 61)]
    rows = pack_arcs(arcs, _scale)
    # all disjoint -> one row, ordered by start time regardless of input order
    assert [p.arc["arc_number"] for p in rows[0]] == [1, 3, 2]
    assert pack_arcs(arcs, _scale) == rows  # stable
