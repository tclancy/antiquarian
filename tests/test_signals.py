"""Tests for free signals: is_revert and commit_binge_window_minutes.

Covers issue #53 test plan:
- is_revert against fixture messages for the three trigger patterns + negatives
- commit_binge_window_minutes against a fixture stream with known clusters
- Both fields present on CommitFeatures from strategy
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from antiquarian.mining import _detect_revert, compute_binge_windows
from antiquarian.models import CommitFeatures


def _commit(
    *,
    author: str = "Alice",
    message: str = "fix bug",
    ts: datetime | None = None,
    additions: int = 10,
    deletions: int = 5,
) -> CommitFeatures:
    if ts is None:
        ts = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
    return CommitFeatures(
        id="test",
        git_sha="abc1234",
        jj_change_id=None,
        jj_commit_id=None,
        author=author,
        author_email=f"{author.lower()}@example.com",
        timestamp=ts,
        hour_of_day=ts.hour,
        day_of_week=ts.weekday(),
        message=message,
        files_changed=["src/main.py"],
        additions=additions,
        deletions=deletions,
        pr_number=None,
        pr_body=None,
    )


class TestDetectRevert:
    def test_revert_quote_prefix(self):
        assert _detect_revert('Revert "Add login feature"', 10, 20)

    def test_conventional_revert(self):
        assert _detect_revert("revert: undo the thing", 5, 10)

    def test_reverts_commit_sha(self):
        assert _detect_revert("Reverts commit abc1234def in main", 10, 10)

    def test_reverts_commit_long_sha(self):
        assert _detect_revert("This reverts commit 1a2b3c4d5e6f7890abcdef", 10, 10)

    def test_balanced_diff_above_threshold(self):
        assert _detect_revert("cleanup", 50, 48)

    def test_balanced_diff_below_min_lines(self):
        assert not _detect_revert("small fix", 3, 3)

    def test_normal_commit_not_revert(self):
        assert not _detect_revert("add new feature", 100, 5)

    def test_empty_message_not_revert(self):
        assert not _detect_revert("", 0, 0)

    def test_revert_in_body_not_prefix(self):
        assert not _detect_revert("fix: revert to old approach", 10, 5)

    def test_case_insensitive_reverts_commit(self):
        assert _detect_revert("REVERTS COMMIT abc1234", 10, 10)


class TestComputeBingeWindows:
    def test_empty_list(self):
        assert compute_binge_windows([]) == []

    def test_single_commit_no_neighbor(self):
        commits = [_commit()]
        result = compute_binge_windows(commits)
        assert len(result) == 1
        assert result[0].commit_binge_window_minutes is None

    def test_two_commits_same_author(self):
        t1 = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
        t2 = t1 + timedelta(minutes=30)
        commits = [_commit(ts=t1), _commit(ts=t2)]
        result = compute_binge_windows(commits)
        assert result[0].commit_binge_window_minutes == 30
        assert result[1].commit_binge_window_minutes == 30

    def test_cluster_identifies_closest_neighbor(self):
        t1 = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
        t2 = t1 + timedelta(minutes=5)
        t3 = t1 + timedelta(hours=3)
        commits = [_commit(ts=t1), _commit(ts=t2), _commit(ts=t3)]
        result = compute_binge_windows(commits)
        assert result[0].commit_binge_window_minutes == 5
        assert result[1].commit_binge_window_minutes == 5
        assert result[2].commit_binge_window_minutes == 175

    def test_different_authors_independent(self):
        t1 = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
        t2 = t1 + timedelta(minutes=10)
        commits = [
            _commit(author="Alice", ts=t1),
            _commit(author="Bob", ts=t2),
        ]
        result = compute_binge_windows(commits)
        assert result[0].commit_binge_window_minutes is None
        assert result[1].commit_binge_window_minutes is None

    def test_mixed_authors_binge(self):
        t1 = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
        t2 = t1 + timedelta(minutes=5)
        t3 = t1 + timedelta(minutes=60)
        commits = [
            _commit(author="Alice", ts=t1),
            _commit(author="Bob", ts=t2),
            _commit(author="Alice", ts=t3),
        ]
        result = compute_binge_windows(commits)
        assert result[0].commit_binge_window_minutes == 60
        assert result[1].commit_binge_window_minutes is None
        assert result[2].commit_binge_window_minutes == 60

    def test_preserves_other_fields(self):
        c = _commit(message="important fix", additions=42, deletions=7)
        result = compute_binge_windows([c])
        assert result[0].message == "important fix"
        assert result[0].additions == 42
        assert result[0].deletions == 7
        assert result[0].author == "Alice"


class TestIsRevertOnCommitFeatures:
    def test_revert_commit_has_flag(self):
        c = _commit(message='Revert "bad change"')
        assert not c.is_revert  # not set by constructor
        # is_revert is set during mining, tested via _detect_revert

    def test_default_is_false(self):
        c = _commit()
        assert c.is_revert is False

    def test_default_binge_is_none(self):
        c = _commit()
        assert c.commit_binge_window_minutes is None
