"""Tests for the region profiler — build_regions().

Fixtures per issue #52 test plan:
- Simple directory structure with clear regions
- Root-level files (no subdirectory)
- First-touch attribution (introduced_in)
- Notable evolutions (large diffs relative to region history)
- Empty commit list
- Single commit
- Multiple commits in one region
"""

from __future__ import annotations

from datetime import datetime, timezone

from antiquarian.models import CommitFeatures
from antiquarian.profile import build_regions


def _commit(
    *,
    sha: str = "abc1234",
    author: str = "Alice",
    message: str = "fix bug",
    files: list[str] | None = None,
    additions: int = 10,
    deletions: int = 5,
    ts: datetime | None = None,
) -> CommitFeatures:
    if ts is None:
        ts = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
    return CommitFeatures(
        id=f"test-{sha}",
        git_sha=sha,
        jj_change_id=None,
        jj_commit_id=None,
        author=author,
        author_email=f"{author.lower()}@example.com",
        timestamp=ts,
        hour_of_day=ts.hour,
        day_of_week=ts.weekday(),
        message=message,
        files_changed=files or ["src/main.py"],
        additions=additions,
        deletions=deletions,
        pr_number=None,
        pr_body=None,
    )


class TestEmptyInput:
    def test_empty_list_returns_empty(self):
        assert build_regions([]) == []


class TestBasicDirectoryGrouping:
    def test_single_region(self):
        commits = [
            _commit(files=["src/app.py"]),
            _commit(files=["src/utils.py"]),
        ]
        regions = build_regions(commits)
        assert len(regions) == 1
        assert regions[0].name == "src"
        assert regions[0].path_prefix == "src/"

    def test_multiple_regions(self):
        commits = [
            _commit(files=["src/app.py"]),
            _commit(files=["tests/test_app.py"]),
            _commit(files=["docs/readme.md"]),
        ]
        regions = build_regions(commits)
        names = {r.name for r in regions}
        assert names == {"src", "tests", "docs"}

    def test_root_level_files_omitted(self):
        commits = [
            _commit(files=["README.md", "setup.py"]),
            _commit(files=["src/app.py"]),
        ]
        regions = build_regions(commits)
        names = {r.name for r in regions}
        assert "src" in names
        assert "." not in names

    def test_nested_dirs_group_by_top_level(self):
        commits = [
            _commit(files=["src/models/user.py"]),
            _commit(files=["src/views/home.py"]),
            _commit(files=["src/utils.py"]),
        ]
        regions = build_regions(commits)
        assert len(regions) == 1
        assert regions[0].name == "src"

    def test_commit_touching_multiple_regions(self):
        commits = [
            _commit(files=["src/app.py", "tests/test_app.py", "docs/api.md"]),
        ]
        regions = build_regions(commits)
        names = {r.name for r in regions}
        assert names == {"src", "tests", "docs"}


class TestFirstTouchAttribution:
    def test_introduced_in_is_earliest_commit(self):
        commits = [
            _commit(
                sha="second",
                files=["src/utils.py"],
                ts=datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc),
            ),
            _commit(
                sha="first",
                files=["src/app.py"],
                ts=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
            ),
        ]
        regions = build_regions(commits)
        src = next(r for r in regions if r.name == "src")
        assert src.introduced_in == "first"

    def test_different_regions_different_first_touch(self):
        commits = [
            _commit(
                sha="src-first",
                files=["src/app.py"],
                ts=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
            ),
            _commit(
                sha="tests-first",
                files=["tests/test_app.py"],
                ts=datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc),
            ),
        ]
        regions = build_regions(commits)
        src = next(r for r in regions if r.name == "src")
        tests = next(r for r in regions if r.name == "tests")
        assert src.introduced_in == "src-first"
        assert tests.introduced_in == "tests-first"


class TestNotableEvolutions:
    def test_large_diff_flagged(self):
        small_commits = [
            _commit(
                sha=f"small-{i}",
                files=["src/app.py"],
                additions=10,
                deletions=5,
                ts=datetime(2025, 1, i + 1, 10, 0, tzinfo=timezone.utc),
            )
            for i in range(10)
        ]
        big_commit = _commit(
            sha="big-one",
            files=["src/app.py"],
            additions=1000,
            deletions=500,
            ts=datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc),
        )
        commits = small_commits + [big_commit]
        regions = build_regions(commits)
        src = next(r for r in regions if r.name == "src")
        assert "big-one" in src.notable_evolutions

    def test_no_notable_when_uniform(self):
        commits = [
            _commit(
                sha=f"c-{i}",
                files=["src/app.py"],
                additions=10,
                deletions=5,
                ts=datetime(2025, 1, i + 1, 10, 0, tzinfo=timezone.utc),
            )
            for i in range(10)
        ]
        regions = build_regions(commits)
        src = next(r for r in regions if r.name == "src")
        assert src.notable_evolutions == []

    def test_single_commit_region_no_notable(self):
        commits = [_commit(sha="only", files=["lib/helper.py"])]
        regions = build_regions(commits)
        lib = next(r for r in regions if r.name == "lib")
        assert lib.notable_evolutions == []


class TestSorting:
    def test_regions_sorted_by_commit_count_descending(self):
        commits = [
            _commit(sha="s1", files=["src/a.py"]),
            _commit(sha="s2", files=["src/b.py"]),
            _commit(sha="s3", files=["src/c.py"]),
            _commit(sha="t1", files=["tests/a.py"]),
            _commit(sha="d1", files=["docs/x.md"]),
        ]
        regions = build_regions(commits)
        assert regions[0].name == "src"


class TestEdgeCases:
    def test_no_git_sha_uses_id(self):
        c = CommitFeatures(
            id="test-no-sha",
            git_sha=None,
            jj_change_id=None,
            jj_commit_id=None,
            author="Alice",
            author_email="alice@example.com",
            timestamp=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
            hour_of_day=10,
            day_of_week=0,
            message="fix",
            files_changed=["src/app.py"],
            additions=10,
            deletions=5,
            pr_number=None,
            pr_body=None,
        )
        regions = build_regions([c])
        src = next(r for r in regions if r.name == "src")
        assert src.introduced_in == "test-no-sha"

    def test_only_root_files_returns_empty(self):
        commits = [_commit(files=["README.md"]), _commit(files=["setup.py"])]
        regions = build_regions(commits)
        assert regions == []
