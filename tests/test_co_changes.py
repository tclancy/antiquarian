"""Tests for the file co-change profiler — build_co_changes() + related_files().

Issue #48 — pairs that change together carry coupling signal that single-file
ownership stats can't see. Pairs with high co-change counts often reflect
architectural coupling, paired test files, or migration partners.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from antiquarian.models import CoChange, CommitFeatures
from antiquarian.profile import build_co_changes, related_files

from tests.strategies import commit_features


def _commit(
    *,
    sha: str = "abc1234",
    files: list[str] | None = None,
    timestamp: datetime | None = None,
    additions: int = 5,
    deletions: int = 2,
) -> CommitFeatures:
    return CommitFeatures(
        id=f"id-{sha}",
        git_sha=sha,
        jj_change_id=None,
        jj_commit_id=None,
        author="dev",
        author_email="dev@example.com",
        timestamp=timestamp or datetime(2026, 1, 1, tzinfo=timezone.utc),
        hour_of_day=10,
        day_of_week=2,
        message="m",
        files_changed=files or ["a.py"],
        additions=additions,
        deletions=deletions,
        pr_number=None,
        pr_body=None,
    )


class TestBuildCoChanges:
    def test_empty_commits(self):
        assert build_co_changes([]) == []

    def test_single_file_commits_have_no_pairs(self):
        commits = [
            _commit(sha="a", files=["x.py"]),
            _commit(sha="b", files=["y.py"]),
        ]
        assert build_co_changes(commits) == []

    def test_two_file_commit_produces_one_pair(self):
        t = datetime(2026, 1, 15, tzinfo=timezone.utc)
        commits = [_commit(sha="a", files=["b.py", "a.py"], timestamp=t)]
        result = build_co_changes(commits)
        assert len(result) == 1
        cc = result[0]
        # Canonical order: file_a < file_b
        assert cc.file_a == "a.py"
        assert cc.file_b == "b.py"
        assert cc.count == 1
        assert cc.last_co_changed_at == t

    def test_three_file_commit_produces_three_pairs(self):
        commits = [_commit(sha="a", files=["a.py", "b.py", "c.py"])]
        result = build_co_changes(commits)
        assert len(result) == 3
        pairs = {(c.file_a, c.file_b) for c in result}
        assert pairs == {("a.py", "b.py"), ("a.py", "c.py"), ("b.py", "c.py")}

    def test_pair_count_accumulates_across_commits(self):
        commits = [
            _commit(sha="a", files=["x.py", "y.py"]),
            _commit(sha="b", files=["x.py", "y.py"]),
            _commit(sha="c", files=["x.py", "y.py"]),
        ]
        result = build_co_changes(commits)
        assert len(result) == 1
        assert result[0].count == 3

    def test_last_co_changed_at_is_max_timestamp(self):
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 6, 15, tzinfo=timezone.utc)
        t3 = datetime(2026, 3, 1, tzinfo=timezone.utc)
        commits = [
            _commit(sha="a", files=["x.py", "y.py"], timestamp=t1),
            _commit(sha="b", files=["x.py", "y.py"], timestamp=t2),
            _commit(sha="c", files=["x.py", "y.py"], timestamp=t3),
        ]
        result = build_co_changes(commits)
        assert result[0].last_co_changed_at == t2

    def test_sorted_by_count_desc_then_alphabetical(self):
        commits = [
            _commit(sha="1", files=["a.py", "b.py"]),  # AB count=2
            _commit(sha="2", files=["a.py", "b.py"]),
            _commit(sha="3", files=["c.py", "d.py"]),  # CD count=1
            _commit(sha="4", files=["a.py", "c.py"]),  # AC count=1
        ]
        result = build_co_changes(commits)
        assert [(c.file_a, c.file_b, c.count) for c in result] == [
            ("a.py", "b.py", 2),
            ("a.py", "c.py", 1),
            ("c.py", "d.py", 1),
        ]

    def test_mega_commit_filtered_out(self):
        big = [f"f{i}.py" for i in range(60)]
        normal = ["x.py", "y.py"]
        commits = [
            _commit(sha="big", files=big),
            _commit(sha="ok", files=normal),
        ]
        result = build_co_changes(commits)
        # Only the small commit's pair survives
        assert len(result) == 1
        assert (result[0].file_a, result[0].file_b) == ("x.py", "y.py")

    def test_mega_commit_threshold_tunable(self):
        big = ["a.py", "b.py", "c.py", "d.py"]
        commits = [_commit(sha="big", files=big)]
        # Default cap (50) keeps it
        assert len(build_co_changes(commits)) == 6
        # Tighter cap (3) drops it
        assert build_co_changes(commits, max_files_per_commit=3) == []

    def test_duplicate_files_in_single_commit_deduped(self):
        commits = [_commit(sha="a", files=["x.py", "x.py", "y.py"])]
        result = build_co_changes(commits)
        assert len(result) == 1
        assert result[0].count == 1

    def test_canonical_pair_ordering_regardless_of_input_order(self):
        c1 = _commit(sha="a", files=["z.py", "a.py"])
        c2 = _commit(sha="b", files=["a.py", "z.py"])
        for commit in (c1, c2):
            result = build_co_changes([commit])
            assert result[0].file_a == "a.py"
            assert result[0].file_b == "z.py"

    def test_no_self_pairs(self):
        commits = [_commit(sha="a", files=["x.py", "y.py", "z.py"])]
        result = build_co_changes(commits)
        for cc in result:
            assert cc.file_a != cc.file_b

    def test_commit_shas_recorded(self):
        commits = [
            _commit(sha="abc11111", files=["x.py", "y.py"]),
            _commit(sha="def22222", files=["x.py", "y.py"]),
        ]
        result = build_co_changes(commits)
        assert len(result) == 1
        assert result[0].commit_shas == ("abc11111", "def22222")

    def test_commit_shas_fall_back_to_uid_when_no_git_sha(self):
        """If a CommitFeatures has no git_sha, the project-native id is used."""
        c = CommitFeatures(
            id="01ULIDLIKE",
            git_sha=None,
            jj_change_id=None,
            jj_commit_id=None,
            author="dev",
            author_email="d@e.com",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            hour_of_day=10,
            day_of_week=2,
            message="m",
            files_changed=["a.py", "b.py"],
            additions=1,
            deletions=0,
            pr_number=None,
            pr_body=None,
        )
        result = build_co_changes([c])
        assert result[0].commit_shas == ("01ULIDLIKE",)

    def test_count_equals_len_commit_shas(self):
        """Invariant: count is always derivable from commit_shas."""
        commits = [_commit(sha=f"sha{i:02d}", files=["x.py", "y.py"]) for i in range(7)]
        result = build_co_changes(commits)
        assert result[0].count == len(result[0].commit_shas)

    def test_triple_recoverable_from_pair_intersections(self):
        """The motivating use case from issue #48 review.

        Pair counts alone can't distinguish "one commit touched A, B, C"
        from "three separate AB / AC / BC commits." With commit_shas
        retained, intersecting two pairs' SHA sets recovers the triple
        exactly.
        """
        # Scenario A: one triple commit + three pair commits
        commits = [
            _commit(sha="triple00", files=["a.py", "b.py", "c.py"]),
            _commit(sha="ab000001", files=["a.py", "b.py"]),
            _commit(sha="ac000001", files=["a.py", "c.py"]),
            _commit(sha="bc000001", files=["b.py", "c.py"]),
        ]
        pairs = {(cc.file_a, cc.file_b): cc for cc in build_co_changes(commits)}
        ab = set(pairs[("a.py", "b.py")].commit_shas)
        ac = set(pairs[("a.py", "c.py")].commit_shas)
        bc = set(pairs[("b.py", "c.py")].commit_shas)
        # Intersection across all three pair-evidence sets recovers
        # commits that touched all three files
        triple_commits = ab & ac & bc
        assert triple_commits == {"triple00"}

        # Scenario B: same pair counts (2/2/2) but no shared commit
        commits_b = [
            _commit(sha="ab000001", files=["a.py", "b.py"]),
            _commit(sha="ab000002", files=["a.py", "b.py"]),
            _commit(sha="ac000001", files=["a.py", "c.py"]),
            _commit(sha="ac000002", files=["a.py", "c.py"]),
            _commit(sha="bc000001", files=["b.py", "c.py"]),
            _commit(sha="bc000002", files=["b.py", "c.py"]),
        ]
        pairs_b = {(cc.file_a, cc.file_b): cc for cc in build_co_changes(commits_b)}
        ab = set(pairs_b[("a.py", "b.py")].commit_shas)
        ac = set(pairs_b[("a.py", "c.py")].commit_shas)
        bc = set(pairs_b[("b.py", "c.py")].commit_shas)
        # No commit touched all three
        assert ab & ac & bc == set()


class TestRelatedFiles:
    def _sample_pairs(self) -> list[CoChange]:
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)

        def shas(n: int) -> tuple[str, ...]:
            return tuple(f"sha{i}" for i in range(n))

        return [
            CoChange("a.py", "b.py", 5, t, shas(5)),
            CoChange("a.py", "c.py", 3, t, shas(3)),
            CoChange("a.py", "d.py", 1, t, shas(1)),
            CoChange("b.py", "c.py", 2, t, shas(2)),
            CoChange("c.py", "d.py", 4, t, shas(4)),
        ]

    def test_empty_input(self):
        assert related_files("a.py", []) == []

    def test_no_match_returns_empty(self):
        assert related_files("nonexistent.py", self._sample_pairs()) == []

    def test_finds_pairs_on_either_side(self):
        """file_path may appear as file_a or file_b in the canonical ordering."""
        # a.py is file_a in three pairs
        result = related_files("a.py", self._sample_pairs())
        assert [(o, c) for o, c in result] == [
            ("b.py", 5),
            ("c.py", 3),
            ("d.py", 1),
        ]
        # c.py appears as file_b in some pairs and file_a in others
        result = related_files("c.py", self._sample_pairs())
        assert ("a.py", 3) in result
        assert ("b.py", 2) in result
        assert ("d.py", 4) in result

    def test_top_n_caps_output(self):
        result = related_files("a.py", self._sample_pairs(), top_n=2)
        assert len(result) == 2
        # Top 2 by count
        assert result == [("b.py", 5), ("c.py", 3)]

    def test_sorted_by_count_desc(self):
        result = related_files("c.py", self._sample_pairs())
        counts = [c for _, c in result]
        assert counts == sorted(counts, reverse=True)


class TestBuildCoChangesProperties:
    """Hypothesis invariants — must hold for any input shape."""

    @given(commits=st.lists(commit_features(), max_size=20))
    @settings(max_examples=50)
    def test_canonical_pair_ordering(self, commits) -> None:
        """Every CoChange has file_a < file_b lexicographically."""
        for cc in build_co_changes(commits):
            assert cc.file_a < cc.file_b

    @given(commits=st.lists(commit_features(), max_size=20))
    @settings(max_examples=50)
    def test_no_self_pairs(self, commits) -> None:
        for cc in build_co_changes(commits):
            assert cc.file_a != cc.file_b

    @given(commits=st.lists(commit_features(), max_size=20))
    @settings(max_examples=50)
    def test_unique_pairs(self, commits) -> None:
        """Each unordered pair appears at most once in the output."""
        result = build_co_changes(commits)
        pairs = [(c.file_a, c.file_b) for c in result]
        assert len(pairs) == len(set(pairs))

    @given(commits=st.lists(commit_features(), max_size=20))
    @settings(max_examples=50)
    def test_count_at_least_one(self, commits) -> None:
        """Every pair in output was seen in at least one commit."""
        for cc in build_co_changes(commits):
            assert cc.count >= 1

    @given(commits=st.lists(commit_features(), max_size=20))
    @settings(max_examples=50)
    def test_sorted_by_count_desc(self, commits) -> None:
        result = build_co_changes(commits)
        counts = [c.count for c in result]
        assert counts == sorted(counts, reverse=True)

    @given(commits=st.lists(commit_features(), max_size=10))
    @settings(max_examples=30)
    def test_deterministic(self, commits) -> None:
        """Same input → same output, byte-for-byte."""
        assert build_co_changes(commits) == build_co_changes(commits)

    @given(commits=st.lists(commit_features(), max_size=15))
    @settings(max_examples=50)
    def test_count_equals_len_commit_shas(self, commits) -> None:
        """The two ought to be the same for every output record."""
        for cc in build_co_changes(commits):
            assert cc.count == len(cc.commit_shas)
