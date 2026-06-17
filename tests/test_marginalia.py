"""Tests for the marginalia (TODO/FIXME) atom reframe (#122).

Kept in its own module so it doesn't share the tail of test_render.py with
other in-flight work — the atom's behaviour (rename, demotion, density floor)
is a self-contained concern.
"""

from __future__ import annotations

from antiquarian.render import _ATOM_ORDER, render_todo_strip


def _todo(text: str, age_days: int, *, path: str = "src/a.py", line: int = 10) -> dict:
    return {
        "file_path": path,
        "kind": "TODO",
        "line_number": line,
        "text": text,
        "introduced_sha": "deadbeefcafe",
        "introduced_short": "deadbeef",
        "introduced_at": "2020-01-01T00:00:00+00:00",
        "introduced_by": "Ada",
        "age_days": age_days,
    }


class TestMarginaliaReframe:
    """The TODO atom is reframed as marginalia, demoted, density-floored (#122)."""

    def _timeline(self) -> dict:
        return {
            "full_span": {
                "start": "2020-01-01T00:00:00+00:00",
                "end": "2026-01-01T00:00:00+00:00",
                "days": 2192,
            },
            "active_windows": [],
            "gaps": [],
        }

    def test_heading_no_longer_accusatory(self):
        todos = [_todo(f"t{i}", 100 + i) for i in range(3)]
        out = render_todo_strip(todos, self._timeline())
        assert "admissions" not in out.lower()
        assert "margins" in out.lower()

    def test_below_floor_renders_a_note_not_a_chart(self):
        out = render_todo_strip([_todo("implement auth-int", 2471)], self._timeline())
        assert "marginalia-note" in out
        assert "implement auth-int" in out
        assert "a.py" in out
        assert "<rect" not in out  # no chart furniture

    def test_at_floor_renders_the_chart(self):
        todos = [_todo(f"t{i}", 100 + i) for i in range(3)]
        out = render_todo_strip(todos, self._timeline())
        assert "marginalia-note" not in out
        assert "<rect" in out  # the bar chart

    def test_empty_still_skips(self):
        assert render_todo_strip([], self._timeline()) == ""

    def test_atom_demoted_to_last(self):
        assert _ATOM_ORDER[-1] == "todo_strip"
