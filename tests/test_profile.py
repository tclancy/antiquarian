"""Tests for the person profiler — build_author_baselines().

Hand-built fixtures per issue #49 test plan:
- Single author across many commits
- Multiple authors with overlapping regions
- Sparse author (1 commit)
- Author with weekday-only commits
- Empty commit list
"""

from __future__ import annotations

from datetime import datetime, timezone

from antiquarian.models import CommitFeatures
from antiquarian.profile import build_author_baselines


def _commit(
    *,
    author: str = "Alice",
    hour: int = 10,
    day: int = 0,
    message: str = "fix bug",
    files: list[str] | None = None,
    ts: datetime | None = None,
) -> CommitFeatures:
    if ts is None:
        ts = datetime(2025, 6, 1, hour, 0, tzinfo=timezone.utc)
    return CommitFeatures(
        id="test",
        git_sha="abc1234",
        jj_change_id=None,
        jj_commit_id=None,
        author=author,
        author_email=f"{author.lower()}@example.com",
        timestamp=ts,
        hour_of_day=hour,
        day_of_week=day,
        message=message,
        files_changed=files or ["src/main.py"],
        additions=10,
        deletions=5,
        pr_number=None,
        pr_body=None,
    )


class TestEmptyInput:
    def test_empty_list_returns_empty_dict(self):
        assert build_author_baselines([]) == {}


class TestSingleAuthor:
    def test_baseline_computed_cleanly(self):
        commits = [
            _commit(
                hour=9,
                day=0,
                message="initial commit",
                files=["src/app.py", "tests/test_app.py"],
                ts=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc),
            ),
            _commit(
                hour=14,
                day=2,
                message="add feature",
                files=["src/app.py"],
                ts=datetime(2025, 3, 1, 14, 0, tzinfo=timezone.utc),
            ),
            _commit(
                hour=11,
                day=4,
                message="refactor src/utils.py and src/app.py",
                files=["src/utils.py", "src/app.py"],
                ts=datetime(2025, 6, 1, 11, 0, tzinfo=timezone.utc),
            ),
        ]
        baselines = build_author_baselines(commits)
        assert len(baselines) == 1

        b = baselines["Alice"]
        assert b.author == "Alice"
        assert b.sample_size == 3
        assert b.commit_share == 1.0
        assert b.tenure_days == (datetime(2025, 6, 1) - datetime(2025, 1, 1)).days
        assert b.median_message_len == len("initial commit")
        assert b.median_files_changed == 2
        assert b.typical_hours == (9, 14)
        assert set(b.typical_days) == {0, 2, 4}

    def test_regions_touched(self):
        commits = [
            _commit(files=["src/app.py", "src/utils.py"]),
            _commit(files=["tests/test_app.py"]),
            _commit(files=["src/models.py"]),
        ]
        baselines = build_author_baselines(commits)
        regions = baselines["Alice"].regions_touched
        assert regions["src"] == 2
        assert regions["tests"] == 1

    def test_path_word_ratio(self):
        commits = [
            _commit(message="fix src/app.py broken import"),
            _commit(message="this is a plain message"),
        ]
        baselines = build_author_baselines(commits)
        ratio = baselines["Alice"].path_word_ratio
        assert 0 < ratio < 1

    def test_root_files_use_dot_region(self):
        commits = [_commit(files=["README.md", "setup.py"])]
        baselines = build_author_baselines(commits)
        assert "." in baselines["Alice"].regions_touched


class TestMultipleAuthors:
    def test_overlapping_regions(self):
        commits = [
            _commit(author="Alice", files=["src/app.py"]),
            _commit(author="Bob", files=["src/utils.py"]),
            _commit(author="Alice", files=["tests/test_app.py"]),
            _commit(author="Bob", files=["src/app.py", "tests/test_utils.py"]),
        ]
        baselines = build_author_baselines(commits)
        assert len(baselines) == 2

        assert baselines["Alice"].sample_size == 2
        assert baselines["Bob"].sample_size == 2
        assert baselines["Alice"].commit_share == 0.5
        assert baselines["Bob"].commit_share == 0.5

        assert "src" in baselines["Alice"].regions_touched
        assert "src" in baselines["Bob"].regions_touched

    def test_unequal_shares(self):
        commits = [
            _commit(author="Alice"),
            _commit(author="Alice"),
            _commit(author="Alice"),
            _commit(author="Bob"),
        ]
        baselines = build_author_baselines(commits)
        assert baselines["Alice"].commit_share == 0.75
        assert baselines["Bob"].commit_share == 0.25


class TestSparseAuthor:
    def test_single_commit_baseline(self):
        commits = [
            _commit(
                hour=15,
                day=3,
                message="one-off fix",
                files=["lib/helper.py"],
                ts=datetime(2025, 4, 10, 15, 0, tzinfo=timezone.utc),
            ),
        ]
        baselines = build_author_baselines(commits)
        b = baselines["Alice"]
        assert b.sample_size == 1
        assert b.tenure_days == 0
        assert b.commit_share == 1.0
        assert b.median_message_len == len("one-off fix")
        assert b.median_files_changed == 1
        assert b.typical_hours == (15, 15)
        assert b.typical_days == (3,)
        assert b.regions_touched == {"lib": 1}


class TestTypicalDays:
    def test_weekday_only_author(self):
        commits = []
        for i in range(20):
            day = i % 5  # Mon-Fri
            commits.append(_commit(day=day))
        baselines = build_author_baselines(commits)
        assert set(baselines["Alice"].typical_days) == {0, 1, 2, 3, 4}

    def test_weekend_only_author(self):
        commits = [
            _commit(day=5),
            _commit(day=5),
            _commit(day=6),
            _commit(day=6),
        ]
        baselines = build_author_baselines(commits)
        assert set(baselines["Alice"].typical_days) == {5, 6}

    def test_mostly_weekday_with_noise(self):
        commits = [_commit(day=d % 5) for d in range(50)]
        commits.append(_commit(day=6))
        baselines = build_author_baselines(commits)
        typical = set(baselines["Alice"].typical_days)
        assert {0, 1, 2, 3, 4}.issubset(typical)
        assert 6 not in typical


class TestTypicalHours:
    def test_concentrated_hours(self):
        commits = [_commit(hour=h) for h in [9, 10, 10, 11, 14]]
        baselines = build_author_baselines(commits)
        low, high = baselines["Alice"].typical_hours
        assert low <= 10
        assert high >= 11

    def test_single_hour(self):
        commits = [_commit(hour=22)]
        baselines = build_author_baselines(commits)
        assert baselines["Alice"].typical_hours == (22, 22)


class TestPathWordRatio:
    def test_all_path_tokens(self):
        commits = [_commit(message="src/a.py tests/b.py lib/c.rs")]
        baselines = build_author_baselines(commits)
        assert baselines["Alice"].path_word_ratio == 1.0

    def test_no_path_tokens(self):
        commits = [_commit(message="fix the broken thing")]
        baselines = build_author_baselines(commits)
        assert baselines["Alice"].path_word_ratio == 0.0

    def test_empty_messages(self):
        commits = [_commit(message=""), _commit(message="")]
        baselines = build_author_baselines(commits)
        assert baselines["Alice"].path_word_ratio == 0.0
