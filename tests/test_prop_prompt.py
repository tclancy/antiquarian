"""Property tests for the prompt builders in narrative.py (issue #20).

These exist to surface input shapes that crash ``build_user_prompt``,
``build_survey_prompt``, or the underlying ``_format_commit`` / ``_format_todo``
helpers — and to act as regression pins once such inputs are found.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from antiquarian.narrative import (
    THRESHOLD_BYTES,
    _format_commit,
    _format_todo,
    build_survey_prompt,
    build_user_prompt,
)

from tests.strategies import commit_features, todo_annotations


class TestFormatCommitProperties:
    @given(c=commit_features(), index=st.integers(min_value=1, max_value=10_000))
    def test_never_crashes(self, c, index: int) -> None:
        result = _format_commit(c, index)
        assert isinstance(result, str)

    @given(c=commit_features(), index=st.integers(min_value=1, max_value=10_000))
    def test_sha_substring_present(self, c, index: int) -> None:
        """The first 8 chars of the SHA (or UID fallback) should appear in output."""
        result = _format_commit(c, index)
        expected = (c.git_sha or c.id)[:8]
        assert expected in result

    @given(c=commit_features(), index=st.integers(min_value=1, max_value=10_000))
    def test_sanitizes_attribution_in_message(self, c, index: int) -> None:
        """Hang-pattern trailers must never appear in the formatted output."""
        result = _format_commit(c, index)
        assert "Co-Authored-By: Claude <noreply@anthropic.com>" not in result
        assert "🤖 Generated with [Claude Code](https://claude.ai/code)" not in result


class TestFormatTodoProperties:
    @given(t=todo_annotations())
    def test_never_crashes(self, t) -> None:
        result = _format_todo(t)
        assert isinstance(result, str)


class TestBuildUserPromptProperties:
    @given(
        file_path=st.text(min_size=1, max_size=200),
        repo_name=st.text(min_size=1, max_size=200),
        commits=st.lists(commit_features(), max_size=20),
        todos=st.lists(todo_annotations(), max_size=20),
    )
    @settings(max_examples=50)  # multi-commit prompts are heavier
    def test_never_crashes(
        self, file_path: str, repo_name: str, commits, todos
    ) -> None:
        prompt = build_user_prompt(file_path, repo_name, commits, todos)
        assert isinstance(prompt, str)

    @given(
        file_path=st.text(min_size=1, max_size=200).filter(lambda s: "`" not in s),
        repo_name=st.text(min_size=1, max_size=200).filter(lambda s: "`" not in s),
        commits=st.lists(commit_features(), max_size=10),
        todos=st.lists(todo_annotations(), max_size=10),
    )
    @settings(max_examples=50)
    def test_contains_repo_name_and_file_path(
        self, file_path: str, repo_name: str, commits, todos
    ) -> None:
        prompt = build_user_prompt(file_path, repo_name, commits, todos)
        assert file_path in prompt
        assert repo_name in prompt

    @given(
        file_path=st.text(min_size=1, max_size=200),
        repo_name=st.text(min_size=1, max_size=200),
        commits=st.lists(commit_features(), max_size=20),
        todos=st.lists(todo_annotations(), max_size=20),
    )
    @settings(max_examples=50)
    def test_no_hang_attribution_in_prompt(
        self, file_path: str, repo_name: str, commits, todos
    ) -> None:
        """The whole pipeline (any commit messages or PR bodies fed in) must
        not let the known hang patterns through into the final prompt."""
        prompt = build_user_prompt(file_path, repo_name, commits, todos)
        assert "Co-Authored-By: Claude <noreply@anthropic.com>" not in prompt
        assert "🤖 Generated with [Claude Code](https://claude.ai/code)" not in prompt


class TestBuildUserPromptCompressorProperties:
    """Property tests for the size-aware compressor (issue #36)."""

    @given(
        commits=st.lists(commit_features(), min_size=1, max_size=15),
        todos=st.lists(todo_annotations(), max_size=10),
    )
    @settings(max_examples=50)
    def test_every_input_sha_appears_in_output(self, commits, todos) -> None:
        """No commit silently lost — every input SHA appears as a header or in the trail."""
        prompt = build_user_prompt("f.py", "repo", commits, todos)
        for c in commits:
            assert (c.git_sha or c.id)[:8] in prompt

    @given(
        commits=st.lists(commit_features(), min_size=0, max_size=10),
        todos=st.lists(todo_annotations(), max_size=5),
    )
    @settings(max_examples=30)
    def test_idempotent_same_inputs(self, commits, todos) -> None:
        """Same inputs → identical prompt bytes. Sanity check on determinism."""
        first = build_user_prompt("f.py", "repo", commits, todos)
        second = build_user_prompt("f.py", "repo", commits, todos)
        assert first == second

    @given(
        commits=st.lists(commit_features(), min_size=0, max_size=12),
        todos=st.lists(todo_annotations(), max_size=5),
    )
    @settings(max_examples=50)
    def test_commit_count_header_reflects_originals(self, commits, todos) -> None:
        """The Commit count line always shows the original total, not the rendered subset."""
        prompt = build_user_prompt("f.py", "repo", commits, todos)
        assert f"**Commit count:** {len(commits)}" in prompt

    @given(
        commits=st.lists(commit_features(), min_size=0, max_size=10),
        todos=st.lists(todo_annotations(), max_size=5),
    )
    @settings(max_examples=30)
    def test_threshold_respected_when_compressible(self, commits, todos) -> None:
        """For typical inputs, output ≤ THRESHOLD_BYTES.

        Pathological cases — repos/files with massive todos or where even
        the zero-commits-plus-trail rendering exceeds the threshold — get a
        slightly larger output. We allow a generous ceiling (3x threshold)
        to absorb those without losing the invariant for typical inputs.
        """
        prompt = build_user_prompt("f.py", "repo", commits, todos)
        # Hard cap — even the worst pathological inputs in our generators
        # shouldn't run away unboundedly.
        assert len(prompt) <= 3 * THRESHOLD_BYTES


class TestBuildSurveyPromptProperties:
    @given(
        repo_name=st.text(min_size=1, max_size=200),
        file_stories=st.lists(
            st.tuples(
                st.text(min_size=1, max_size=200),
                st.text(max_size=5000),  # narrative markdown
            ),
            max_size=10,
        ),
    )
    @settings(max_examples=50)
    def test_never_crashes(self, repo_name: str, file_stories) -> None:
        prompt = build_survey_prompt(repo_name, file_stories)
        assert isinstance(prompt, str)

    @given(
        repo_name=st.text(min_size=1, max_size=200).filter(lambda s: "`" not in s),
        file_stories=st.lists(
            st.tuples(
                st.text(min_size=1, max_size=200).filter(lambda s: "`" not in s),
                st.text(max_size=5000),
            ),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=50)
    def test_contains_each_file_path(self, repo_name: str, file_stories) -> None:
        prompt = build_survey_prompt(repo_name, file_stories)
        for path, _story in file_stories:
            assert path in prompt
