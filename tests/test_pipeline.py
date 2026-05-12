"""Tests for pipeline orchestration — generate_file_story and generate_codebase_survey.

All tests mock subprocess.run (the claude -p call) and git operations so they
run without network access, a real Claude subscription, or a populated repo.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from antiquarian.models import CommitFeatures, TodoAnnotation
from antiquarian.pipeline import generate_codebase_survey, generate_file_story


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
    @patch("antiquarian.pipeline.synthesize_narrative", return_value="## Origin\nNarrative here.")
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


class TestGenerateSurvey:
    def test_empty_file_list_raises(self, tmp_repo: Path):
        with pytest.raises(ValueError, match="at least one"):
            generate_codebase_survey(tmp_repo, [])

    @patch("antiquarian.pipeline.synthesize_survey", return_value="## Files surveyed\nSynthesis.")
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_happy_path(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        story_path = tmp_repo / ".antiquarian" / "stories" / "a.md"
        story_path.parent.mkdir(parents=True, exist_ok=True)
        story_path.write_text("Story A")
        mock_story.return_value = ("Story A", story_path)

        (tmp_repo / "a.py").write_text("x = 1\n")
        (tmp_repo / "b.py").write_text("y = 2\n")

        survey, survey_path = generate_codebase_survey(
            tmp_repo, ["a.py", "b.py"]
        )

        assert "Synthesis" in survey
        assert survey_path.exists()
        assert survey_path.parent.name == "surveys"
        assert mock_story.call_count == 2
        mock_survey.assert_called_once()
        stories_arg = mock_survey.call_args.kwargs["file_stories"]
        assert len(stories_arg) == 2

    @patch("antiquarian.pipeline.synthesize_survey", return_value="## Files surveyed\nDone.")
    @patch("antiquarian.pipeline.generate_file_story")
    @patch("antiquarian.pipeline.detect_github_repo", return_value=None)
    def test_log_callback_invoked(
        self,
        mock_gh: MagicMock,
        mock_story: MagicMock,
        mock_survey: MagicMock,
        tmp_repo: Path,
    ):
        mock_story.return_value = ("s", tmp_repo / "x.md")
        (tmp_repo / "a.py").write_text("")

        messages: list[str] = []
        generate_codebase_survey(tmp_repo, ["a.py"], log=messages.append)

        assert any("[survey]" in m for m in messages)
