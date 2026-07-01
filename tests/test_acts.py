"""Tests for structural Act segmentation — build_acts() / assign_arcs_to_acts() (#149).

The segmentation is a transparent heuristic tuned at the calibration gate, so these
tests pin the *contract* (count bounds, contiguity, confidence range, which signal
fires when a movement is unambiguous) rather than exact boundary positions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from antiquarian.models import CommitFeatures
from antiquarian.profile import _is_human_author, assign_arcs_to_acts, build_acts

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _c(day: int, author: str = "Alice", email: str | None = None) -> CommitFeatures:
    return CommitFeatures(
        id=f"u{day}-{author}",
        git_sha=f"sha{day:04d}",
        jj_change_id=None,
        jj_commit_id=None,
        author=author,
        author_email=email or f"{author.lower()}@example.com",
        timestamp=_EPOCH + timedelta(days=day),
        hour_of_day=10,
        day_of_week=0,
        message="work",
        files_changed=["src/main.py"],
        additions=10,
        deletions=5,
        pr_number=None,
        pr_body=None,
    )


class TestDegenerate:
    def test_empty_is_empty(self):
        assert build_acts([]) == []

    def test_too_few_commits_is_one_act(self):
        acts = build_acts([_c(d) for d in range(5)])  # < _ACT_MIN_COMMITS
        assert len(acts) == 1
        assert acts[0].index == 1
        assert acts[0].signals == ("origin",)
        assert acts[0].boundary_confidence == 1.0

    def test_steady_solo_history_is_one_act(self):
        # One author, even cadence, no second human → no movement to claim.
        acts = build_acts([_c(d * 10) for d in range(20)])
        assert len(acts) == 1
        assert acts[0].commit_count == 20


class TestSegmentation:
    def test_second_human_creates_a_boundary(self):
        alice = [_c(d, "Alice") for d in range(0, 180, 6)]  # first half
        bob = [_c(d, "Bob") for d in range(200, 360, 6)]  # joins later
        acts = build_acts(alice + bob)
        assert len(acts) >= 2
        assert any("second-human" in a.signals for a in acts[1:])

    def test_bot_second_author_does_not_count_as_a_human_boundary(self):
        alice = [_c(d, "Alice") for d in range(0, 180, 6)]
        bot = [
            _c(d, "dependabot[bot]", "bot@users.noreply.github.com")
            for d in range(200, 360, 6)
        ]
        acts = build_acts(alice + bot)
        # A bot joining is not the arrival of a second *human* contributor.
        assert not any("second-human" in a.signals for a in acts)

    def test_short_history_is_one_act_even_with_a_second_human(self):
        # A 3-day life is a single movement; the guard beats the second-human
        # signal (a short burst of work isn't an "Act 2").
        acts = build_acts(
            [_c(0, "Alice") for _ in range(10)] + [_c(3, "Bob") for _ in range(10)]
        )
        assert len(acts) == 1

    def test_no_act_is_a_sliver(self):
        # Every Act spans at least ~8% of the timeline (scale-relative floor).
        alice = [_c(d, "Alice") for d in range(0, 180, 6)]
        bob = [_c(d, "Bob") for d in range(200, 360, 6)]
        acts = build_acts(alice + bob)
        total_days = (acts[-1].end - acts[0].start).days
        assert min((a.end - a.start).days for a in acts) >= 0.075 * total_days

    def test_count_is_capped_at_five(self):
        # Alternating burst/quiet plus staggered authors → many candidates.
        commits: list[CommitFeatures] = []
        for block in range(8):
            author = f"Dev{block % 4}"
            density = 2 if block % 2 == 0 else 25
            base = block * 45
            commits += [_c(base + (i * 45 // density), author) for i in range(density)]
        acts = build_acts(commits)
        assert 1 <= len(acts) <= 5

    def test_acts_are_contiguous_and_cover_the_span(self):
        alice = [_c(d, "Alice") for d in range(0, 180, 6)]
        bob = [_c(d, "Bob") for d in range(200, 360, 6)]
        ordered = sorted(alice + bob, key=lambda c: c.timestamp)
        acts = build_acts(ordered)
        assert acts[0].start == ordered[0].timestamp
        assert acts[-1].end == ordered[-1].timestamp
        for earlier, later in zip(acts, acts[1:]):
            assert earlier.end == later.start  # no gaps, no overlaps
        assert [a.index for a in acts] == list(range(1, len(acts) + 1))

    def test_confidence_always_in_unit_range(self):
        alice = [_c(d, "Alice") for d in range(0, 180, 6)]
        bob = [_c(d, "Bob") for d in range(200, 360, 6)]
        acts = build_acts(alice + bob)
        assert all(0.0 <= a.boundary_confidence <= 1.0 for a in acts)
        assert acts[0].boundary_confidence == 1.0  # the origin is not a guess

    def test_ids_are_unique(self):
        acts = build_acts(
            [_c(d, "Alice") for d in range(0, 180, 6)]
            + [_c(d, "Bob") for d in range(200, 360, 6)]
        )
        assert len({a.id for a in acts}) == len(acts)


class TestHumanDetection:
    def test_people_are_human(self):
        assert _is_human_author("Alice", "alice@example.com")

    def test_bots_and_agents_are_not(self):
        assert not _is_human_author("dependabot[bot]", "x@bot.com")
        assert not _is_human_author("github-actions", "actions@github.com")
        assert not _is_human_author("dispatch-bot", "bot@x.com")


class TestArcAttachment:
    def _acts(self):
        return build_acts(
            [_c(d, "Alice") for d in range(0, 180, 6)]
            + [_c(d, "Bob") for d in range(200, 360, 6)]
        )

    def test_arc_lands_in_the_act_it_overlaps(self):
        acts = self._acts()
        early = _EPOCH + timedelta(days=30)
        late = _EPOCH + timedelta(days=300)
        mapping = assign_arcs_to_acts(acts, {"early-arc": [early], "late-arc": [late]})
        act_for = {a.id: a for a in acts}
        assert (
            act_for[mapping["early-arc"]].start
            <= early
            <= act_for[mapping["early-arc"]].end
        )
        assert (
            act_for[mapping["late-arc"]].start
            <= late
            <= act_for[mapping["late-arc"]].end
        )
        assert mapping["early-arc"] != mapping["late-arc"]

    def test_undatable_arc_is_skipped(self):
        acts = self._acts()
        assert "ghost" not in assign_arcs_to_acts(acts, {"ghost": []})

    def test_single_act_absorbs_everything(self):
        acts = build_acts([_c(d) for d in range(5)])
        mapping = assign_arcs_to_acts(acts, {"a": [_EPOCH + timedelta(days=1)]})
        assert mapping["a"] == acts[0].id
