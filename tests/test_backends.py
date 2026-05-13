"""Tests for the pluggable narrative backend interface (#30)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from antiquarian.backends import DEFAULT_BACKEND, ClaudePBackend, NarrativeBackend


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["claude"], returncode=0, stdout=stdout, stderr=""
    )


class TestClaudePBackend:
    def test_synthesize_calls_subprocess_with_system_and_user_prompts(self) -> None:
        backend = ClaudePBackend()
        with patch(
            "antiquarian.narrative.subprocess.run",
            return_value=_completed("the narrative"),
        ) as mock_run:
            out = backend.synthesize(
                "SYSTEM",
                "USER",
                timeout_seconds=60,
                sleep=lambda _s: None,
            )
        assert out == "the narrative"
        # Verify the subprocess invocation looked right
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[0] == "claude"
        assert cmd[1] == "-p"
        assert "--system-prompt" in cmd
        assert "SYSTEM" in cmd
        assert kwargs["input"] == "USER"
        assert kwargs["timeout"] == 60

    def test_strips_stdout_whitespace(self) -> None:
        backend = ClaudePBackend()
        with patch(
            "antiquarian.narrative.subprocess.run",
            return_value=_completed("  padded  \n\n"),
        ):
            out = backend.synthesize("S", "U", sleep=lambda _s: None)
        assert out == "padded"


class TestNarrativeBackendProtocol:
    def test_claude_p_backend_satisfies_protocol(self) -> None:
        assert isinstance(ClaudePBackend(), NarrativeBackend)

    def test_default_backend_is_claude_p(self) -> None:
        assert isinstance(DEFAULT_BACKEND, ClaudePBackend)

    def test_custom_backend_can_replace_default(self) -> None:
        """A user-supplied backend with the right shape is honored."""
        from antiquarian.narrative import synthesize_narrative

        class StubBackend:
            def __init__(self):
                self.received: list[tuple[str, str]] = []

            def synthesize(
                self,
                system_prompt,
                user_prompt,
                *,
                timeout_seconds=300,
                log=lambda _m: None,
            ):
                self.received.append((system_prompt, user_prompt))
                return "## Origin\nStubbed."

        stub = StubBackend()
        out = synthesize_narrative(
            file_path="src/x.py",
            repo_name="acme/repo",
            commits=[],
            todos=[],
            backend=stub,
        )
        assert out == "## Origin\nStubbed."
        assert len(stub.received) == 1
        system, user = stub.received[0]
        assert "historian" in system.lower()  # SYSTEM_PROMPT made it through
        assert "src/x.py" in user  # user prompt contains the file path
