"""Pluggable narrative backends — the seam between antiquarian and any LLM (#30).

The default backend is ``ClaudePBackend``, which wraps the ``claude -p`` CLI
subprocess plus the retry/backoff helper from ``narrative.py``. Other backends
(direct Anthropic SDK, OpenAI, local model, etc.) can be added by implementing
the same ``NarrativeBackend`` Protocol.

Why a Protocol rather than a base class: duck-typed extension fits the
"bring your own AI" use case better than inheritance, and runtime checks
(``isinstance``) still work via ``@runtime_checkable`` when needed.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol, runtime_checkable

from antiquarian.narrative import _run_claude_p


def _noop(_msg: str) -> None:
    pass


@runtime_checkable
class NarrativeBackend(Protocol):
    """A backend that synthesizes narrative text from a system + user prompt.

    Implementations are responsible for their own retry/timeout/error handling.
    The caller (``synthesize_narrative`` / ``synthesize_survey``) decides only
    the prompts and the timeout budget; everything else is the backend's call.
    """

    def synthesize(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout_seconds: int = 300,
        log: Callable[[str], None] = _noop,
    ) -> str:
        """Return the synthesized narrative text. Raise on unrecoverable failure."""
        ...


class ClaudePBackend:
    """Default backend — wraps the ``claude -p`` CLI subprocess.

    Inherits the retry/backoff behavior from ``_run_claude_p`` (#31 + #39):
    transient ``TimeoutExpired`` and ``CalledProcessError`` are retried with
    separate caps; everything else propagates.
    """

    def synthesize(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout_seconds: int = 300,
        log: Callable[[str], None] = _noop,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        result = _run_claude_p(
            ["claude", "-p", "--system-prompt", system_prompt],
            user_prompt,
            timeout_seconds,
            log=log,
            sleep=sleep,
        )
        return result.stdout.strip()


# The default — used by synthesize_narrative / synthesize_survey when no
# backend is passed in. A singleton is fine because the backend itself is
# stateless; injecting one is the only way to override it.
DEFAULT_BACKEND: NarrativeBackend = ClaudePBackend()
