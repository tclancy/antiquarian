"""Tests for the statistical baseline SC detector."""

from __future__ import annotations

from datetime import datetime, timezone

from antiquarian.detect import (
    StatisticalBaselineDetector,
    SignificantChangeDetector,
    _hour_distance,
    _z_score,
)
from antiquarian.models import CommitFeatures, SignificantChange
from antiquarian.profile import build_author_baselines


def _commit(
    *,
    author: str = "Alice",
    message: str = "fix: small change",
    files: list[str] | None = None,
    additions: int = 5,
    deletions: int = 3,
    hour: int = 10,
    day: int = 2,
    ts: datetime | None = None,
) -> CommitFeatures:
    if ts is None:
        ts = datetime(2024, 6, 15, hour, 0, tzinfo=timezone.utc)
    return CommitFeatures(
        id=f"test-{hash((author, message, hour))}",
        git_sha=f"abc{hash((author, message, hour)):08x}"[:10],
        jj_change_id=None,
        jj_commit_id=None,
        author=author,
        author_email=f"{author.lower()}@example.com",
        timestamp=ts,
        hour_of_day=hour,
        day_of_week=day,
        message=message,
        files_changed=files or ["src/app.py"],
        additions=additions,
        deletions=deletions,
        pr_number=None,
        pr_body=None,
    )


class TestProtocol:
    def test_detector_satisfies_protocol(self):
        det = StatisticalBaselineDetector()
        assert isinstance(det, SignificantChangeDetector)


class TestHourDistance:
    def test_inside_range(self):
        assert _hour_distance(10, 9, 14) == 0

    def test_at_boundary(self):
        assert _hour_distance(9, 9, 14) == 0
        assert _hour_distance(14, 9, 14) == 0

    def test_outside_above(self):
        assert _hour_distance(17, 9, 14) == 3

    def test_outside_below(self):
        assert _hour_distance(6, 9, 14) == 3

    def test_wrap_around(self):
        dist = _hour_distance(2, 22, 23)
        assert dist == 3

    def test_same_hour_range(self):
        assert _hour_distance(10, 10, 10) == 0
        assert _hour_distance(11, 10, 10) == 1


class TestZScore:
    def test_zero_stdev(self):
        assert _z_score(5.0, 3.0, 0.0) == 0.0

    def test_positive_z(self):
        z = _z_score(15.0, 10.0, 2.5)
        assert z == 2.0

    def test_negative_z(self):
        z = _z_score(5.0, 10.0, 2.5)
        assert z == -2.0


class TestEmptyInput:
    def test_empty_commits(self):
        det = StatisticalBaselineDetector()
        assert det.detect([], {}) == []

    def test_no_matching_baselines(self):
        det = StatisticalBaselineDetector()
        commits = [_commit(author="Alice")]
        assert det.detect(commits, {}) == []


class TestSingleAuthorBasicDetection:
    def _make_normal_commits(self, n: int = 10) -> list[CommitFeatures]:
        return [
            _commit(
                message=f"fix: routine change {i}",
                files=["src/app.py"],
                additions=5,
                deletions=3,
                hour=10,
                day=2,
            )
            for i in range(n)
        ]

    def test_outlier_message_length_detected(self):
        normal = self._make_normal_commits(10)
        outlier = _commit(
            message="x" * 500,
            files=["src/app.py"],
            additions=5,
            deletions=3,
            hour=10,
            day=2,
        )
        commits = normal + [outlier]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        assert len(results) > 0
        top = results[0]
        assert outlier.git_sha in top.commits
        assert any("message" in r for r in top.reasons)

    def test_outlier_files_changed_detected(self):
        normal = self._make_normal_commits(10)
        outlier = _commit(
            message="fix: big refactor",
            files=[f"src/file{i}.py" for i in range(20)],
            additions=5,
            deletions=3,
            hour=10,
            day=2,
        )
        commits = normal + [outlier]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        assert len(results) > 0
        top = results[0]
        assert outlier.git_sha in top.commits
        assert any("files" in r.lower() for r in top.reasons)

    def test_outlier_diff_size_detected(self):
        normal = self._make_normal_commits(10)
        outlier = _commit(
            message="fix: small change",
            files=["src/app.py"],
            additions=5000,
            deletions=3000,
            hour=10,
            day=2,
        )
        commits = normal + [outlier]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        assert len(results) > 0
        top = results[0]
        assert outlier.git_sha in top.commits
        assert any("diff" in r.lower() for r in top.reasons)

    def test_outlier_hour_detected(self):
        normal = self._make_normal_commits(10)
        outlier = _commit(
            message="fix: small change",
            files=["src/app.py"],
            additions=5,
            deletions=3,
            hour=3,
            day=2,
        )
        commits = normal + [outlier]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        assert len(results) > 0
        shas = [sc.commits[0] for sc in results]
        assert outlier.git_sha in shas

    def test_outlier_day_detected(self):
        normal = [
            _commit(
                message=f"fix: change {i}",
                day=d,
            )
            for i in range(10)
            for d in [0, 1, 2, 3, 4]  # Mon-Fri
        ]
        outlier = _commit(
            message="fix: weekend hotfix",
            day=6,  # Sunday
        )
        commits = normal + [outlier]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        shas = [sc.commits[0] for sc in results]
        assert outlier.git_sha in shas


class TestMultipleAuthors:
    def test_each_author_scored_against_own_baseline(self):
        alice_commits = [
            _commit(author="Alice", message=f"fix: small {i}", additions=5)
            for i in range(10)
        ]
        bob_commits = [
            _commit(author="Bob", message=f"feat: big refactor {i}", additions=500)
            for i in range(10)
        ]
        alice_outlier = _commit(author="Alice", message="fix: tiny", additions=5000)
        bob_normal = _commit(author="Bob", message="feat: routine big", additions=600)

        commits = alice_commits + bob_commits + [alice_outlier, bob_normal]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)

        top_shas = [sc.commits[0] for sc in results[:5]]
        assert alice_outlier.git_sha in top_shas


class TestTopN:
    def test_respects_top_n_limit(self):
        commits = [
            _commit(message=f"fix: change {i}", additions=i * 100) for i in range(50)
        ]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines, top_n=5)
        assert len(results) <= 5

    def test_top_n_zero_returns_empty(self):
        commits = [
            _commit(message=f"fix: change {i}", additions=i * 100) for i in range(10)
        ]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines, top_n=0)
        assert results == []


class TestOutputShape:
    def test_significant_change_fields(self):
        normal = [_commit(message=f"fix: small {i}", additions=5) for i in range(10)]
        outlier = _commit(message="x" * 500, additions=5000)
        commits = normal + [outlier]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        assert len(results) > 0
        sc_item = results[0]
        assert isinstance(sc_item, SignificantChange)
        assert sc_item.detector_name == "statistical"
        assert len(sc_item.commits) == 1
        assert isinstance(sc_item.score, float)
        assert sc_item.score > 0
        assert len(sc_item.reasons) > 0
        assert all(isinstance(r, str) for r in sc_item.reasons)

    def test_reasons_are_concrete(self):
        normal = [_commit(message=f"fix: small {i}", additions=5) for i in range(10)]
        outlier = _commit(message="x" * 500, additions=5)
        commits = normal + [outlier]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        for sc_item in results:
            for reason in sc_item.reasons:
                assert "unusual" not in reason.lower()
                assert len(reason) > 10


class TestEdgeCases:
    def test_single_commit_author(self):
        commits = [_commit(author="Solo")]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        assert isinstance(results, list)

    def test_identical_commits(self):
        commits = [_commit(message="fix: same", additions=5) for _ in range(20)]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        assert all(sc.score == 0 or len(sc.reasons) > 0 for sc in results)

    def test_empty_message_commit(self):
        normal = [_commit(message=f"fix: change {i}") for i in range(10)]
        outlier = _commit(message="")
        commits = normal + [outlier]
        baselines = build_author_baselines(commits)
        det = StatisticalBaselineDetector()
        results = det.detect(commits, baselines)
        assert isinstance(results, list)
