"""Tests for pipeline orchestration — generate_file_story and generate_codebase_survey.

All tests mock subprocess.run (the claude -p call) and git operations so they
run without network access, a real Claude subscription, or a populated repo.
"""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from antiquarian.cache import open_cache
from antiquarian.models import CommitFeatures
from antiquarian.pipeline import (
    _stub_narrative_for_skipped,
    generate_codebase_survey,
    generate_file_story,
)


def _fake_commit(sha: str, file_path: str = "src/thing.py") -> CommitFeatures:
    return CommitFeatures(
        id=f"id-{sha}",
        git_sha=sha,
        jj_change_id=None,
        jj_commit_id=None,
        author="dev",
        author_email="dev@example.com",
        timestamp=datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc),
        hour_of_day=14,
        day_of_week=1,
        message=f"commit {sha}",
        files_changed=[file_path],
        additions=10,
        deletions=2,
        pr_number=None,
        pr_body=None,
    )


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with a tracked file."""
    (tmp_path / ".git").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    target = src / "thing.py"
    target.write_text("print('hello')\n")
    return tmp_path


class TestGenerateFileStory:
    def test_file_not_found_raises(self, tmp_repo: Path):
        with pytest.raises(FileNotFoundError, match="no_such_file.py"):
            generate_file_story(tmp_repo, "no_such_file.py")

    @patch("antiquarian.pipeline.extract_todos", return_value=iter([]))
    @patch("antiquarian.pipeline.mine_file_history")
    @patch("antiquarian.pipeline.historical_shas", return_value=["aaa111"])
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    @patch(
        "antiquarian.pipeline.synthesize_narrative",
        return_value="## Origin\nNarrative here.",
    )
    def test_happy_path(
        self,
        mock_synth: MagicMock,
        mock_gh: MagicMock,
        mock_shas: MagicMock,
        mock_mine: MagicMock,
        mock_todos: MagicMock,
        tmp_repo: Path,
    ):
        mock_mine.return_value = iter([_fake_commit("aaa111")])

        narrative, story_path = generate_file_story(tmp_repo, "src/thing.py")

        assert "Narrative here" in narrative
        assert story_path.exists()
        assert story_path.name == "src__thing.py.md"
        mock_synth.assert_called_once()

    @patch("antiquarian.pipeline.extract_todos", return_value=iter([]))
    @patch("antiquarian.pipeline.mine_file_history")
    @patch("antiquarian.pipeline.historical_shas", return_value=["aaa111"])
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    @patch("antiquarian.pipeline.synthesize_narrative", return_value="cached story")
    @patch("antiquarian.pipeline.get_commit")
    def test_cache_hit_skips_mining(
        self,
        mock_get: MagicMock,
        mock_synth: MagicMock,
        mock_gh: MagicMock,
        mock_shas: MagicMock,
        mock_mine: MagicMock,
        mock_todos: MagicMock,
        tmp_repo: Path,
    ):
        mock_get.return_value = _fake_commit("aaa111")
        mock_mine.return_value = iter([])

        narrative, _ = generate_file_story(tmp_repo, "src/thing.py")

        assert narrative == "cached story"
        mock_mine.assert_not_called()


class TestStoryDiskCache:
    """Issue #35 — reuse on-disk story when commit set + TODOs unchanged."""

    @patch("antiquarian.pipeline.extract_todos", return_value=iter([]))
    @patch("antiquarian.pipeline.mine_file_history")
    @patch("antiquarian.pipeline.historical_shas", return_value=["aaa111"])
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    @patch(
        "antiquarian.pipeline.synthesize_narrative",
        return_value="## Origin\nFresh narrative.",
    )
    def test_first_run_persists_with_digest_marker(
        self,
        mock_synth: MagicMock,
        mock_gh: MagicMock,
        mock_shas: MagicMock,
        mock_mine: MagicMock,
        mock_todos: MagicMock,
        tmp_repo: Path,
    ):
        mock_mine.return_value = iter([_fake_commit("aaa111")])
        _, story_path = generate_file_story(tmp_repo, "src/thing.py")
        content = story_path.read_text(encoding="utf-8")
        assert content.startswith("<!-- antiquarian-cache-digest: ")
        assert "## Origin" in content
        mock_synth.assert_called_once()

    @patch("antiquarian.pipeline.extract_todos", return_value=iter([]))
    @patch("antiquarian.pipeline.mine_file_history")
    @patch("antiquarian.pipeline.historical_shas", return_value=["aaa111"])
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    @patch("antiquarian.pipeline.synthesize_narrative")
    def test_second_run_reuses_cached_story_when_commits_unchanged(
        self,
        mock_synth: MagicMock,
        mock_gh: MagicMock,
        mock_shas: MagicMock,
        mock_mine: MagicMock,
        mock_todos: MagicMock,
        tmp_repo: Path,
    ):
        mock_mine.return_value = iter([_fake_commit("aaa111")])
        mock_synth.return_value = "## Origin\nNarrative."
        narrative_1, story_path = generate_file_story(tmp_repo, "src/thing.py")
        assert "Narrative." in narrative_1
        assert mock_synth.call_count == 1

        # Second run — same commit set. Should reuse.
        mock_mine.return_value = iter([])
        mock_synth.return_value = "## Origin\nDIFFERENT (should not appear)."
        with patch(
            "antiquarian.pipeline.get_commit", return_value=_fake_commit("aaa111")
        ):
            narrative_2, _ = generate_file_story(tmp_repo, "src/thing.py")
        assert "Narrative." in narrative_2
        assert "DIFFERENT" not in narrative_2
        assert mock_synth.call_count == 1  # not called again

    @patch("antiquarian.pipeline.extract_todos", return_value=iter([]))
    @patch("antiquarian.pipeline.mine_file_history")
    @patch("antiquarian.pipeline.historical_shas")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    @patch("antiquarian.pipeline.synthesize_narrative")
    def test_new_commit_invalidates_cached_story(
        self,
        mock_synth: MagicMock,
        mock_gh: MagicMock,
        mock_shas: MagicMock,
        mock_mine: MagicMock,
        mock_todos: MagicMock,
        tmp_repo: Path,
    ):
        mock_shas.return_value = ["aaa111"]
        mock_mine.return_value = iter([_fake_commit("aaa111")])
        mock_synth.return_value = "## Origin\nFirst run."
        generate_file_story(tmp_repo, "src/thing.py")
        assert mock_synth.call_count == 1

        mock_shas.return_value = ["aaa111", "bbb222"]
        mock_mine.return_value = iter([_fake_commit("bbb222")])
        mock_synth.return_value = "## Origin\nSecond run with new commit."
        with patch(
            "antiquarian.pipeline.get_commit", return_value=_fake_commit("aaa111")
        ):
            narrative, _ = generate_file_story(tmp_repo, "src/thing.py")
        assert "Second run" in narrative
        assert mock_synth.call_count == 2

    @patch("antiquarian.pipeline.extract_todos", return_value=iter([]))
    @patch("antiquarian.pipeline.mine_file_history")
    @patch("antiquarian.pipeline.historical_shas", return_value=["aaa111"])
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    @patch("antiquarian.pipeline.synthesize_narrative")
    def test_no_cache_flag_bypasses_story_cache(
        self,
        mock_synth: MagicMock,
        mock_gh: MagicMock,
        mock_shas: MagicMock,
        mock_mine: MagicMock,
        mock_todos: MagicMock,
        tmp_repo: Path,
    ):
        mock_mine.return_value = iter([_fake_commit("aaa111")])
        mock_synth.return_value = "## Origin\nNarrative."
        generate_file_story(tmp_repo, "src/thing.py")
        assert mock_synth.call_count == 1

        mock_mine.return_value = iter([_fake_commit("aaa111")])
        mock_synth.return_value = "## Origin\nRegenerated."
        narrative, _ = generate_file_story(tmp_repo, "src/thing.py", use_cache=False)
        assert "Regenerated" in narrative
        assert mock_synth.call_count == 2

    @patch("antiquarian.pipeline.extract_todos", return_value=iter([]))
    @patch("antiquarian.pipeline.mine_file_history")
    @patch("antiquarian.pipeline.historical_shas", return_value=["aaa111"])
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    @patch(
        "antiquarian.pipeline.synthesize_narrative",
        return_value="## Origin\nFresh.",
    )
    def test_old_format_story_without_marker_is_regenerated(
        self,
        mock_synth: MagicMock,
        mock_gh: MagicMock,
        mock_shas: MagicMock,
        mock_mine: MagicMock,
        mock_todos: MagicMock,
        tmp_repo: Path,
    ):
        stories_dir = tmp_repo / ".antiquarian" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        story_file = stories_dir / "src__thing.py.md"
        story_file.write_text("## Origin\nLegacy story without marker.\n")

        mock_mine.return_value = iter([_fake_commit("aaa111")])
        narrative, _ = generate_file_story(tmp_repo, "src/thing.py")
        assert "Fresh" in narrative
        mock_synth.assert_called_once()


class TestGenerateSurvey:
    def test_empty_file_list_raises(self, tmp_repo: Path):
        with pytest.raises(ValueError, match="at least one"):
            generate_codebase_survey(tmp_repo, [])

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nSynthesis.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_happy_path(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        story_path = tmp_repo / ".antiquarian" / "stories" / "a.md"
        story_path.parent.mkdir(parents=True, exist_ok=True)
        story_path.write_text("Story A")
        mock_story.return_value = ("Story A", story_path)

        (tmp_repo / "a.py").write_text("x = 1\n")
        (tmp_repo / "b.py").write_text("y = 2\n")

        survey, survey_path = generate_codebase_survey(tmp_repo, ["a.py", "b.py"])

        assert "Synthesis" in survey
        assert survey_path.exists()
        assert survey_path.parent.name == "surveys"
        assert mock_story.call_count == 2
        mock_survey.assert_called_once()
        stories_arg = mock_survey.call_args.kwargs["file_stories"]
        assert len(stories_arg) == 2

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_co_changes", return_value=[])
    @patch("antiquarian.pipeline.build_regions", return_value=[])
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_pass_3_signals_passed_to_synthesizer(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_regions: MagicMock,
        mock_co: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        """#54 — survey synth receives regions and co_changes from pipeline."""
        story_path = tmp_repo / "x.md"
        mock_story.return_value = ("story", story_path)
        (tmp_repo / "a.py").write_text("")

        generate_codebase_survey(tmp_repo, ["a.py"])

        kwargs = mock_survey.call_args.kwargs
        assert "regions" in kwargs
        assert "co_changes" in kwargs
        # build_regions and build_co_changes were called once with all_commits
        mock_regions.assert_called_once()
        mock_co.assert_called_once()

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_log_callback_invoked(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        mock_story.return_value = ("s", tmp_repo / "x.md")
        (tmp_repo / "a.py").write_text("")

        messages: list[str] = []
        generate_codebase_survey(tmp_repo, ["a.py"], log=messages.append)

        assert any("[survey]" in m for m in messages)


class TestSurveySkipAndStub:
    """Issue #34 — survey continues past a single file's unrecoverable hang."""

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_timeout_is_stubbed_not_raised(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        """A TimeoutExpired from one file shouldn't sink the whole survey."""
        ok_path = tmp_repo / ".antiquarian" / "stories" / "ok.md"
        ok_path.parent.mkdir(parents=True, exist_ok=True)
        ok_path.write_text("Story OK")
        mock_story.side_effect = [
            ("## Origin\nReal story.", ok_path),
            subprocess.TimeoutExpired(cmd=["claude"], timeout=300),
        ]
        (tmp_repo / "a.py").write_text("")
        (tmp_repo / "b.py").write_text("")

        survey, _ = generate_codebase_survey(tmp_repo, ["a.py", "b.py"])

        assert "Done." in survey
        # Both files still made it into the synthesis call
        stories_arg = mock_survey.call_args.kwargs["file_stories"]
        assert len(stories_arg) == 2
        # The hung file got the stub
        hung_story = dict(stories_arg)["b.py"]
        assert "channel went dark" in hung_story
        assert "timed out" in hung_story

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_called_process_error_is_stubbed(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        err = subprocess.CalledProcessError(returncode=2, cmd=["claude"], stderr="bad")
        mock_story.side_effect = err
        (tmp_repo / "a.py").write_text("")

        survey, _ = generate_codebase_survey(tmp_repo, ["a.py"])

        assert "Done." in survey
        stories_arg = mock_survey.call_args.kwargs["file_stories"]
        assert len(stories_arg) == 1
        stub = stories_arg[0][1]
        assert "channel went dark" in stub
        assert "exited 2" in stub

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_skip_is_logged_for_visibility(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        mock_story.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=300)
        (tmp_repo / "stuck.py").write_text("")

        messages: list[str] = []
        generate_codebase_survey(tmp_repo, ["stuck.py"], log=messages.append)

        assert any("stubbing" in m for m in messages)
        assert any("#34" in m for m in messages)
        # Final summary line counts the skip
        assert any("1 of 1 file(s) stubbed" in m for m in messages)

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_stub_not_persisted_to_disk(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        """A subsequent run should retry — don't cache the failure to disk."""
        mock_story.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=300)
        (tmp_repo / "stuck.py").write_text("")

        generate_codebase_survey(tmp_repo, ["stuck.py"])

        stories_dir = tmp_repo / ".antiquarian" / "stories"
        # The mocked generate_file_story never wrote a story; nothing should
        # have been persisted on its behalf by the survey path either.
        if stories_dir.exists():
            for child in stories_dir.iterdir():
                content = child.read_text(encoding="utf-8")
                assert "channel went dark" not in content


class TestStubNarrative:
    def test_has_four_required_sections(self):
        stub = _stub_narrative_for_skipped("f.py", "claude -p timed out")
        assert "## Origin" in stub
        assert "## Major arcs" in stub
        assert "## TODO/FIXME aging" in stub
        assert "## People & ownership" in stub

    def test_voice_rules_respected(self):
        """Stub uses voice-rule-compliant framing — channel went dark, not 'failed'."""
        stub = _stub_narrative_for_skipped("f.py", "claude -p timed out")
        # Banned vocabulary
        for banned in ("blame", "fault", "culprit", "mistake", "failed to"):
            assert banned not in stub.lower()
        # Hedged language
        assert "could not reconstruct" in stub or "unrecoverable" in stub

    def test_reason_included(self):
        stub = _stub_narrative_for_skipped("f.py", "claude -p exited 2")
        assert "claude -p exited 2" in stub


class TestCacheWALMode:
    """Issue #80 — WAL mode enables safe concurrent reads/writes."""

    def test_open_cache_enables_wal(self, tmp_path: Path):
        db_path = tmp_path / ".antiquarian" / "cache.db"
        with open_cache(db_path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"

    def test_open_cache_sets_busy_timeout(self, tmp_path: Path):
        db_path = tmp_path / ".antiquarian" / "cache.db"
        with open_cache(db_path) as conn:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert timeout == 5000


class TestParallelSurvey:
    """Issue #80 — parallel per-file story generation with ThreadPoolExecutor."""

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nParallel done.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_parallel_produces_same_result_as_sequential(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        story_path = tmp_repo / ".antiquarian" / "stories" / "a.md"
        story_path.parent.mkdir(parents=True, exist_ok=True)
        story_path.write_text("Story")
        mock_story.return_value = ("Story", story_path)
        (tmp_repo / "a.py").write_text("")
        (tmp_repo / "b.py").write_text("")

        survey, _ = generate_codebase_survey(tmp_repo, ["a.py", "b.py"], max_workers=2)

        assert "Parallel done." in survey
        assert mock_story.call_count == 2
        stories_arg = mock_survey.call_args.kwargs["file_stories"]
        assert len(stories_arg) == 2

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_parallel_preserves_file_ordering(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        """File stories must appear in the original file_paths order for deterministic synthesis."""
        stories = {"a.py": "Story A", "b.py": "Story B", "c.py": "Story C"}

        def mock_gen(repo_path, fp, **kwargs):
            return stories[fp], tmp_repo / f"{fp}.md"

        mock_story.side_effect = mock_gen
        for f in stories:
            (tmp_repo / f).write_text("")

        generate_codebase_survey(tmp_repo, ["a.py", "b.py", "c.py"], max_workers=4)

        stories_arg = mock_survey.call_args.kwargs["file_stories"]
        assert [fp for fp, _ in stories_arg] == ["a.py", "b.py", "c.py"]
        assert [s for _, s in stories_arg] == ["Story A", "Story B", "Story C"]

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_parallel_timeout_stubbed_like_sequential(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        ok_path = tmp_repo / ".antiquarian" / "stories" / "ok.md"
        ok_path.parent.mkdir(parents=True, exist_ok=True)
        ok_path.write_text("OK")

        def mock_gen(repo_path, fp, **kwargs):
            if fp == "b.py":
                raise subprocess.TimeoutExpired(cmd=["claude"], timeout=300)
            return "## Origin\nReal.", ok_path

        mock_story.side_effect = mock_gen
        (tmp_repo / "a.py").write_text("")
        (tmp_repo / "b.py").write_text("")

        generate_codebase_survey(tmp_repo, ["a.py", "b.py"], max_workers=2)

        stories_arg = mock_survey.call_args.kwargs["file_stories"]
        assert len(stories_arg) == 2
        assert "channel went dark" in dict(stories_arg)["b.py"]
        assert "Real." in dict(stories_arg)["a.py"]

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_parallel_log_is_threadsafe(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        """No interleaved log lines — each message is a complete string."""
        mock_story.return_value = ("s", tmp_repo / "x.md")
        for name in ("a.py", "b.py", "c.py", "d.py"):
            (tmp_repo / name).write_text("")

        messages: list[str] = []
        lock = threading.Lock()

        def recording_log(msg: str) -> None:
            with lock:
                messages.append(msg)

        generate_codebase_survey(
            tmp_repo,
            ["a.py", "b.py", "c.py", "d.py"],
            max_workers=4,
            log=recording_log,
        )

        assert any("[survey]" in m for m in messages)
        for msg in messages:
            assert isinstance(msg, str)
            assert "\n" not in msg or msg.count("\n") == 0

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_workers_capped_at_file_count(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        """max_workers=8 with 2 files should only use 2 threads."""
        mock_story.return_value = ("s", tmp_repo / "x.md")
        (tmp_repo / "a.py").write_text("")
        (tmp_repo / "b.py").write_text("")

        messages: list[str] = []
        generate_codebase_survey(
            tmp_repo, ["a.py", "b.py"], max_workers=8, log=messages.append
        )

        header = [m for m in messages if "file(s)" in m and "worker" in m]
        assert len(header) == 1
        assert "2 workers" in header[0]

    @patch(
        "antiquarian.pipeline.synthesize_survey",
        return_value="## Files surveyed\nDone.",
    )
    @patch("antiquarian.pipeline.build_author_baselines", return_value={})
    @patch("antiquarian.pipeline.historical_shas", return_value=[])
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=("x", "y"))
    def test_max_workers_1_uses_sequential_path(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_shas: MagicMock,
        mock_baselines: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        """max_workers=1 (default) falls back to sequential loop — no worker count in header."""
        mock_story.return_value = ("s", tmp_repo / "x.md")
        (tmp_repo / "a.py").write_text("")

        messages: list[str] = []
        generate_codebase_survey(tmp_repo, ["a.py"], max_workers=1, log=messages.append)

        header = [m for m in messages if "file(s)" in m and m.startswith("[survey]")]
        assert len(header) >= 1
        assert "x/y: 1 file(s)" in header[0]
        assert "worker" not in header[0]
