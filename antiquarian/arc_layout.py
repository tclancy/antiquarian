"""Pure lane-packing for the named-arcs density timeline (#112).

Turns the arcs list into the fewest horizontal rows such that no two arc
lozenges overlap within a row — classic greedy interval (activity-selection)
packing. No HTML, no SVG; the spine is injected as a ``Callable`` so this is
testable without the renderer. ``render.py`` walks the rows and draws lozenges.
See docs/superpowers/specs/2026-06-17-index-as-map-design.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

#: Minimum horizontal gap (px) between two lozenges sharing a row.
LANE_GAP_PX = 4.0
#: Minimum visible width (px) for a single-commit (zero-span) arc.
MIN_LOZENGE_PX = 3.0


@dataclass(frozen=True)
class PlacedArc:
    """One arc placed on the timeline: the source ``arc`` dict and its px span."""

    arc: dict
    x_start: float
    x_end: float


def _arc_span(arc: dict) -> tuple[datetime, datetime] | None:
    """Earliest/latest datable commit timestamp, or None if the arc has none."""
    stamps = [
        datetime.fromisoformat(c["timestamp"]) for c in arc["commits"] if c["timestamp"]
    ]
    if not stamps:
        return None
    return min(stamps), max(stamps)


def pack_arcs(
    arcs: list[dict],
    scale: Callable[[datetime], float],
    *,
    gap: float = LANE_GAP_PX,
    min_width: float = MIN_LOZENGE_PX,
) -> list[list[PlacedArc]]:
    """Greedy lane-pack datable arcs into non-overlapping rows.

    Each arc is placed in the first row whose last lozenge ends at least ``gap``
    px before this arc starts; otherwise a new row opens. Arcs with no datable
    commits are skipped (the renderer lists them separately). Deterministic:
    arcs are processed sorted by (start, end).
    """
    intervals: list[tuple[float, float, dict]] = []
    for arc in arcs:
        span = _arc_span(arc)
        if span is None:
            continue
        x_start = scale(span[0])
        x_end = scale(span[1])
        if x_end < x_start + min_width:
            x_end = x_start + min_width
        intervals.append((x_start, x_end, arc))

    intervals.sort(key=lambda iv: (iv[0], iv[1]))

    rows: list[list[PlacedArc]] = []
    row_ends: list[float] = []
    for x_start, x_end, arc in intervals:
        placed = False
        for r in range(len(row_ends)):
            if x_start >= row_ends[r] + gap:
                rows[r].append(PlacedArc(arc, x_start, x_end))
                row_ends[r] = x_end
                placed = True
                break
        if not placed:
            rows.append([PlacedArc(arc, x_start, x_end)])
            row_ends.append(x_end)
    return rows
