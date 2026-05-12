"""Property tests for narrative._sanitize_for_claude (issue #20).

The sanitizer's contract:
    1. Idempotent — applying twice equals applying once.
    2. Never crashes on arbitrary text.
    3. Removes the bare ``Co-Authored-By: Claude <noreply@anthropic.com>`` form.
    4. Removes the ``🤖 Generated with [Claude Code](…)`` line.
    5. Preserves the parameterized ``Co-Authored-By: Claude Opus 4.7 …`` form
       (those don't hang ``claude -p`` — known via dispatch-bot[bot] commits).
"""

from __future__ import annotations

from hypothesis import example, given, settings
from hypothesis import strategies as st

from antiquarian.narrative import _sanitize_for_claude

from tests.strategies import commit_messages


# Pinning examples from issue #16 — the BetterBlue founding commit shape.
_BETTERBLUE_FOUNDING_MSG = (
    "Initial release of BetterBlue v1.0\n\n"
    "BetterBlue is a modern iOS app.\n\n"
    "🤖 Generated with [Claude Code](https://claude.ai/code)\n\n"
    "Co-Authored-By: Claude <noreply@anthropic.com>"
)


class TestSanitizerProperties:
    @given(text=st.text(max_size=5000))
    def test_never_crashes(self, text: str) -> None:
        result = _sanitize_for_claude(text)
        assert isinstance(result, str)

    @given(text=commit_messages())
    @example(text=_BETTERBLUE_FOUNDING_MSG)
    def test_idempotent(self, text: str) -> None:
        once = _sanitize_for_claude(text)
        twice = _sanitize_for_claude(once)
        assert once == twice

    @given(text=commit_messages())
    @example(text=_BETTERBLUE_FOUNDING_MSG)
    def test_no_bare_claude_attribution_in_output(self, text: str) -> None:
        out = _sanitize_for_claude(text)
        assert "Co-Authored-By: Claude <noreply@anthropic.com>" not in out

    @given(text=commit_messages())
    @example(text=_BETTERBLUE_FOUNDING_MSG)
    def test_no_robot_attribution_line_in_output(self, text: str) -> None:
        out = _sanitize_for_claude(text)
        assert "🤖 Generated with [Claude Code](https://claude.ai/code)" not in out

    @given(prose=st.text(min_size=1, max_size=500))
    def test_parameterized_coauthor_preserved(self, prose: str) -> None:
        """The model-parameterized attribution form does NOT hang claude -p,
        so the sanitizer must leave it intact (preserves who wrote what)."""
        trailer = "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
        msg = prose + "\n\n" + trailer
        out = _sanitize_for_claude(msg)
        assert trailer in out, (
            f"parameterized form was stripped; sanitizer is too aggressive\n"
            f"input: {msg!r}\noutput: {out!r}"
        )

    @given(prose=st.text(min_size=1, max_size=500).filter(
        lambda s: "🤖" not in s
        and "Claude" not in s
        and "claude.ai" not in s
    ))
    def test_attribution_free_text_unchanged_modulo_whitespace(self, prose: str) -> None:
        """Text with no attribution patterns survives unchanged (modulo the
        ``.strip()`` at the end of the sanitizer)."""
        out = _sanitize_for_claude(prose)
        assert out == prose.strip()

    @settings(max_examples=200)
    @given(text=commit_messages())
    def test_output_length_bounded_by_input(self, text: str) -> None:
        """Sanitizer never INCREASES content. Catches accidental wrapping
        or injection regressions."""
        out = _sanitize_for_claude(text)
        assert len(out) <= len(text)
