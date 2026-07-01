"""Tests for per-file traffic-light pip metrics (#148)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from antiquarian.metrics import (
    bus_factor,
    build_file_metrics,
    churn_rate,
    count_repo_authors,
    recency,
    reference_timestamp,
)
from antiquarian.render import _render_metric_pips, render_story_page

UTC = timezone.utc


def _c(email: str, ts: str) -> dict:
    """Cheap factory for a commit row in the metric input shape."""
    return {"author_email": email, "timestamp": ts}


# ----------------------------------------------------------------------------
# Repo author counting
# ----------------------------------------------------------------------------


def test_count_repo_authors_dedupes_across_files():
    commits = {
        "a.py": [_c("a@x", "2026-01-01T00:00:00+00:00")],
        "b.py": [
            _c("a@x", "2026-02-01T00:00:00+00:00"),
            _c("B@X", "2026-03-01T00:00:00+00:00"),
        ],
    }
    # Email casing collapses; two distinct contributors total.
    assert count_repo_authors(commits) == 2


def test_count_repo_authors_ignores_blank_email():
    commits = {
        "a.py": [
            _c("", "2026-01-01T00:00:00+00:00"),
            _c("a@x", "2026-02-01T00:00:00+00:00"),
        ],
    }
    assert count_repo_authors(commits) == 1


# ----------------------------------------------------------------------------
# Bus factor
# ----------------------------------------------------------------------------


def test_bus_factor_solo_repo_returns_na():
    file_commits = [_c("solo@x", f"2026-0{m}-01T00:00:00+00:00") for m in range(1, 6)]
    m = bus_factor(file_commits, repo_author_count=1)
    assert m.level == "na"
    assert m.display == "solo"


def test_bus_factor_red_when_only_one_contributor_above_threshold():
    # One dominant author, one drive-by under the 10% bar.
    file_commits = [_c("dom@x", "2026-01-01T00:00:00+00:00")] * 10 + [
        _c("driveby@x", "2026-01-02T00:00:00+00:00")
    ]
    m = bus_factor(file_commits, repo_author_count=3)
    assert m.level == "red"
    assert m.value == 1.0


def test_bus_factor_yellow_at_two_qualifying_contributors():
    file_commits = [_c("a@x", "2026-01-01T00:00:00+00:00")] * 3 + [
        _c("b@x", "2026-02-01T00:00:00+00:00")
    ] * 3
    m = bus_factor(file_commits, repo_author_count=3)
    assert m.level == "yellow"
    assert m.value == 2.0


def test_bus_factor_green_at_three_qualifying_contributors():
    file_commits = (
        [_c("a@x", "2026-01-01T00:00:00+00:00")] * 4
        + [_c("b@x", "2026-02-01T00:00:00+00:00")] * 4
        + [_c("c@x", "2026-03-01T00:00:00+00:00")] * 4
    )
    m = bus_factor(file_commits, repo_author_count=5)
    assert m.level == "green"
    assert m.value == 3.0


def test_bus_factor_empty_file_is_na():
    m = bus_factor([], repo_author_count=3)
    assert m.level == "na"
    assert m.value is None


# ----------------------------------------------------------------------------
# Churn
# ----------------------------------------------------------------------------


def test_churn_single_commit_is_na():
    m = churn_rate([_c("a@x", "2026-01-01T00:00:00+00:00")])
    assert m.level == "na"
    assert m.value is None


def test_churn_green_under_4_per_year():
    base = datetime(2023, 1, 1, tzinfo=UTC)
    # 3 commits over ~2 years → ~1.5/yr → green
    commits = [
        _c("a@x", (base + timedelta(days=365 * i)).isoformat()) for i in range(3)
    ]
    m = churn_rate(commits)
    assert m.level == "green"
    assert m.value is not None and m.value < 4.0


def test_churn_yellow_between_4_and_12():
    base = datetime(2025, 1, 1, tzinfo=UTC)
    # 8 commits over 1 year → 8/yr
    commits = [_c("a@x", (base + timedelta(days=45 * i)).isoformat()) for i in range(8)]
    m = churn_rate(commits)
    assert m.level == "yellow"


def test_churn_red_above_12():
    base = datetime(2025, 1, 1, tzinfo=UTC)
    commits = [
        _c("a@x", (base + timedelta(days=20 * i)).isoformat()) for i in range(20)
    ]
    m = churn_rate(commits)
    assert m.level == "red"


def test_churn_same_day_commits_report_na_not_red():
    """Same-day-only files have no measurable lifespan — saying 'extreme churn'
    is a category error. Review feedback (#148): return na with a reason."""
    ts = "2026-01-01T00:00:00+00:00"
    m = churn_rate([_c("a@x", ts) for _ in range(5)])
    assert m.level == "na"
    assert m.value is None
    assert "lifespan" in m.detail.lower()


def test_churn_boundary_exact_4_per_year_is_yellow_not_green():
    """Docstring says ``<4 green``: a rate of exactly 4.0 must be yellow."""
    base = datetime(2025, 1, 1, tzinfo=UTC)
    # 5 commits over exactly 365.25 days → ~4.00/yr
    commits = [
        _c("a@x", "2025-01-01T00:00:00+00:00"),
        _c("a@x", "2025-04-01T00:00:00+00:00"),
        _c("a@x", "2025-07-01T00:00:00+00:00"),
        _c("a@x", "2025-10-01T00:00:00+00:00"),
        _c("a@x", (base + timedelta(days=365)).isoformat()),
    ]
    m = churn_rate(commits)
    # 5 commits / (365/365.25) years ≈ 5.003 → yellow per <4 rubric
    assert m.level == "yellow"


# ----------------------------------------------------------------------------
# Recency
# ----------------------------------------------------------------------------


def test_recency_green_recent_commit():
    ref = datetime(2026, 6, 1, tzinfo=UTC)
    m = recency([_c("a@x", "2026-04-01T00:00:00+00:00")], reference_dt=ref)
    assert m.level == "green"


def test_recency_yellow_between_6_and_24_months():
    ref = datetime(2026, 6, 1, tzinfo=UTC)
    m = recency([_c("a@x", "2025-01-01T00:00:00+00:00")], reference_dt=ref)
    assert m.level == "yellow"


def test_recency_red_over_24_months():
    ref = datetime(2026, 6, 1, tzinfo=UTC)
    m = recency([_c("a@x", "2023-01-01T00:00:00+00:00")], reference_dt=ref)
    assert m.level == "red"


def test_recency_is_reproducible_against_reference_dt_not_wall_clock():
    """Same input → same pip, no matter when we render."""
    ref = datetime(2026, 6, 1, tzinfo=UTC)
    one = recency([_c("a@x", "2026-04-01T00:00:00+00:00")], reference_dt=ref)
    two = recency([_c("a@x", "2026-04-01T00:00:00+00:00")], reference_dt=ref)
    assert one == two


def test_recency_clamps_negative_to_zero():
    """A file last touched *after* the repo reference still renders cleanly."""
    ref = datetime(2026, 1, 1, tzinfo=UTC)
    m = recency([_c("a@x", "2026-06-01T00:00:00+00:00")], reference_dt=ref)
    assert m.level == "green"
    assert m.value == 0.0


def test_recency_displayed_months_match_swatch_at_rounding_boundary():
    """Review feedback #148: 23.7 mo rounds up to '24 mo' for display, so the
    classifier must use the rounded value too — else the user sees '24 mo'
    next to a yellow swatch while the rubric says ≥24 should be red."""
    ref = datetime(2026, 6, 1, tzinfo=UTC)
    # ~23.7 months before ref
    last = ref - timedelta(days=int(23.7 * 30.4375))
    m = recency([_c("a@x", last.isoformat())], reference_dt=ref)
    assert m.display == "24 mo"
    assert m.level == "red", (
        "rounded display crossed the threshold, so the swatch must too"
    )


# ----------------------------------------------------------------------------
# Build + integration
# ----------------------------------------------------------------------------


def test_reference_timestamp_picks_repo_wide_max():
    commits = {
        "a.py": [_c("a@x", "2026-01-01T00:00:00+00:00")],
        "b.py": [_c("b@x", "2026-05-15T00:00:00+00:00")],
    }
    assert reference_timestamp(commits) == datetime(2026, 5, 15, tzinfo=UTC)


def test_reference_timestamp_returns_none_on_empty_data():
    assert reference_timestamp({}) is None
    assert reference_timestamp({"a.py": []}) is None


def test_build_file_metrics_returns_pip_list_per_file():
    commits = {
        "a.py": [_c("a@x", "2026-01-01T00:00:00+00:00")],
        "b.py": [
            _c("a@x", "2026-02-01T00:00:00+00:00"),
            _c("b@x", "2026-03-01T00:00:00+00:00"),
            _c("c@x", "2026-04-01T00:00:00+00:00"),
        ],
    }
    ref = reference_timestamp(commits)
    assert ref is not None
    out = build_file_metrics(commits, ref)
    assert set(out.keys()) == {"a.py", "b.py"}
    for f in out:
        assert [m.name for m in out[f]] == ["bus factor", "churn", "recency"]


def test_build_file_metrics_skips_files_with_no_attributed_commits():
    """Review feedback #148: rather than emit three 'na' dashes, an empty
    file gets an empty pip list so the renderer omits the strip."""
    commits = {
        "alive.py": [
            _c("a@x", "2026-01-01T00:00:00+00:00"),
            _c("b@x", "2026-02-01T00:00:00+00:00"),
        ],
        "untouched.py": [],
    }
    ref = reference_timestamp(commits)
    assert ref is not None
    out = build_file_metrics(commits, ref)
    assert out["untouched.py"] == []
    assert len(out["alive.py"]) == 3


def test_solo_author_repo_all_files_get_na_bus_pip():
    """Tom's rubric branch: solo-author repos suppress the bus pip everywhere."""
    commits = {
        "a.py": [_c("solo@x", f"2026-0{m}-01T00:00:00+00:00") for m in range(1, 5)],
        "b.py": [_c("solo@x", "2026-05-01T00:00:00+00:00")],
    }
    ref = reference_timestamp(commits)
    assert ref is not None
    out = build_file_metrics(commits, ref)
    for pips in out.values():
        bus = next(p for p in pips if p.name == "bus factor")
        assert bus.level == "na", "solo-author repos must not flash red bus pips"


# ----------------------------------------------------------------------------
# Render integration
# ----------------------------------------------------------------------------


def test_render_metric_pips_empty_input_yields_empty_string():
    assert _render_metric_pips(None) == ""
    assert _render_metric_pips([]) == ""


def test_render_metric_pips_emits_one_pip_per_metric():
    pips = [
        {
            "glyph": "🚌",
            "name": "bus factor",
            "level": "red",
            "value": 1.0,
            "display": "1",
            "detail": "x",
        },
        {
            "glyph": "🌪️",
            "name": "churn",
            "level": "yellow",
            "value": 7.0,
            "display": "7.0/yr",
            "detail": "y",
        },
    ]
    html = _render_metric_pips(pips)
    assert html.count('class="metric-pip ') == 2
    assert "metric-pip--red" in html
    assert "metric-pip--yellow" in html
    assert "🚌" in html
    assert "🌪️" in html


def test_render_metric_pips_uses_data_tip_not_native_title():
    # The detail rides in data-tip (drives the CSS tooltip), not the flaky
    # native title — the aria-label still carries the reading for a11y.
    pips = [
        {
            "glyph": "🚌",
            "name": "bus factor",
            "level": "green",
            "value": 3.0,
            "display": "3",
            "detail": "3 contributor(s) hold the file",
        }
    ]
    html = _render_metric_pips(pips)
    assert 'data-tip="bus factor: 3 contributor(s) hold the file"' in html
    assert "title=" not in html  # no native title competing with the CSS tip
    assert 'aria-label="bus factor: 3, green"' in html


def test_render_metric_pips_escapes_user_text():
    pips = [
        {
            "glyph": "🚌",
            "name": "bus<x>",
            "level": "green",
            "value": 1.0,
            "display": "<script>",
            "detail": "y&z",
        }
    ]
    html = _render_metric_pips(pips)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "y&amp;z" in html


def test_render_story_page_omits_strip_when_metrics_absent():
    html = render_story_page("a.py", "# story", "demo")
    # The CSS always defines .metric-pips selectors; what we care about
    # is that no <div> with the class actually gets emitted.
    assert '<div class="metric-pips"' not in html


def test_render_story_page_includes_strip_when_metrics_present():
    pips = [
        {
            "glyph": "🚌",
            "name": "bus factor",
            "level": "na",
            "value": None,
            "display": "—",
            "detail": "n/a",
        }
    ]
    html = render_story_page("a.py", "# story", "demo", metrics=pips)
    assert '<div class="metric-pips"' in html
    assert "metric-pip--na" in html


@pytest.mark.parametrize(
    "level",
    ["green", "yellow", "red", "na"],
)
def test_render_metric_pip_class_includes_every_level(level):
    pips = [
        {
            "glyph": "🚌",
            "name": "bus factor",
            "level": level,
            "value": 1.0,
            "display": "1",
            "detail": "x",
        }
    ]
    html = _render_metric_pips(pips)
    assert f"metric-pip--{level}" in html
