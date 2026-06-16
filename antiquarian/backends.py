"""Pluggable narrative backends — the seam between antiquarian and any LLM (#30).

The default backend is ``ClaudePBackend``, which wraps the ``claude -p`` CLI
subprocess plus the retry/backoff helper from ``narrative.py``. Two more
concrete backends ship today (#91):

- ``AnthropicSDKBackend`` — the direct ``anthropic`` SDK, keyed by
  ``ANTHROPIC_API_KEY``. The "bring your own API key" path.
- ``OllamaBackend`` — a local model served by Ollama. The "no API key, runs
  on your machine" path.
- ``ExoBackend`` — a model served by an Exo cluster via its OpenAI-compatible
  API (#102). The "run it across your own devices" path.

Selection is by short name (``claude-p``, ``anthropic-sdk``, ``ollama``,
``exo``) through ``get_backend``, which honors the precedence
``explicit arg → ANTIQUARIAN_BACKEND env → default (claude-p)``.

Why a Protocol rather than a base class: duck-typed extension fits the
"bring your own AI" use case better than inheritance, and runtime checks
(``isinstance``) still work via ``@runtime_checkable`` when needed.

The ``anthropic`` and ``ollama`` packages are **optional** — they're only
imported when their backend is actually used, so the default ``claude-p``
path carries no extra dependencies. A missing package raises a
``BackendError`` naming the install command.
"""

from __future__ import annotations

import os
import random
import time
from typing import Callable, Protocol, TypeVar, runtime_checkable

from antiquarian.narrative import _run_claude_p


def _noop(_msg: str) -> None:
    pass


class BackendError(RuntimeError):
    """A backend is misconfigured or unavailable.

    Raised for the user-fixable cases — missing API key, missing optional
    package, unknown backend name, unreachable local server — so the CLI can
    present a single clean line rather than a traceback. The message must name
    the exact thing to fix (env var, install command, etc.).
    """


# --- selection -------------------------------------------------------------

#: Env var consulted when no explicit backend name is passed.
BACKEND_ENV_VAR = "ANTIQUARIAN_BACKEND"

#: The backend used when neither an explicit name nor the env var is set.
DEFAULT_BACKEND_NAME = "claude-p"


def resolve_backend_name(explicit: str | None = None) -> str:
    """Resolve the backend name by precedence: arg → env → default.

    An explicit name (e.g. from ``--backend``) always wins. Otherwise the
    ``ANTIQUARIAN_BACKEND`` env var is consulted. With neither set, the
    default ``claude-p`` backend is chosen. Surrounding whitespace is
    stripped; an empty/whitespace value is treated as unset.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    env = os.environ.get(BACKEND_ENV_VAR, "")
    if env.strip():
        return env.strip()
    return DEFAULT_BACKEND_NAME


def available_backends() -> list[str]:
    """The selectable backend names, sorted."""
    return sorted(_BACKENDS)


def get_backend(name: str | None = None) -> NarrativeBackend:
    """Construct the backend for *name* (resolved by precedence).

    Construction is cheap and side-effect-free — it stores config only. Use
    :meth:`preflight` (called by the CLI before any work) to surface a
    missing key / package / server up front rather than mid-run.

    Raises ``BackendError`` for an unknown name.
    """
    resolved = resolve_backend_name(name)
    try:
        factory = _BACKENDS[resolved]
    except KeyError:
        raise BackendError(
            f"Unknown backend '{resolved}'. "
            f"Available: {', '.join(available_backends())}."
        ) from None
    return factory()


# --- retry helper ----------------------------------------------------------

_T = TypeVar("_T")


def _retry_with_backoff(
    fn: Callable[[], _T],
    *,
    transient: tuple[type[BaseException], ...],
    label: str,
    max_attempts: int = 3,
    base_backoff_seconds: float = 5.0,
    log: Callable[[str], None] = _noop,
    sleep: Callable[[float], None] = time.sleep,
) -> _T:
    """Call *fn*, retrying on the *transient* exception types.

    Mirrors the exponential-backoff-with-jitter behavior of
    ``narrative._run_claude_p`` so all backends degrade the same way against a
    momentarily flaky upstream. Non-transient exceptions propagate immediately.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except transient as e:
            attempt += 1
            if attempt < max_attempts:
                delay = base_backoff_seconds * (3 ** (attempt - 1))
                wait = delay + random.uniform(0, delay * 0.2)
                log(
                    f"[{label}] transient failure ({type(e).__name__}: {e}); "
                    f"attempt {attempt}/{max_attempts}, retrying in {wait:.1f}s"
                )
                sleep(wait)
            else:
                log(
                    f"[{label}] failed on all {max_attempts} attempts "
                    f"({type(e).__name__}: {e}); giving up"
                )
                raise


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

    name = "claude-p"

    # No preflight: a missing `claude` CLI surfaces through the existing
    # subprocess error handling in cli.py, and adding a PATH check here would
    # be a behavior change for the default path. Preflight is reserved for the
    # backends where failing late (after minutes of mining) is the real cost.

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


#: Default Anthropic model. Sonnet balances narrative quality against the
#: per-run cost of a BYO-key tool; override with ``ANTIQUARIAN_ANTHROPIC_MODEL``.
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"

#: Upper bound on synthesized tokens. A survey runs ~2000 words; 8192 leaves
#: comfortable headroom without inviting runaway output.
_ANTHROPIC_MAX_TOKENS = 8192


class AnthropicSDKBackend:
    """Direct ``anthropic`` SDK backend — the bring-your-own-API-key path (#91).

    The API key is read from ``ANTHROPIC_API_KEY`` (never a flag, never logged).
    The model defaults to ``claude-sonnet-4-6`` and is overridable via the
    ``ANTIQUARIAN_ANTHROPIC_MODEL`` env var or the ``model`` constructor arg.

    Construction is side-effect-free; the key check and package import happen
    in :meth:`preflight` / :meth:`synthesize`.
    """

    name = "anthropic-sdk"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get(
            "ANTIQUARIAN_ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL
        )

    def _require_key(self) -> str:
        if not self.api_key:
            raise BackendError(
                "The anthropic-sdk backend needs an API key. "
                "Set ANTHROPIC_API_KEY in the environment."
            )
        return self.api_key

    def _import_sdk(self):  # type: ignore[no-untyped-def]
        try:
            import anthropic
        except ImportError as e:
            raise BackendError(
                "The 'anthropic' package is required for the anthropic-sdk "
                "backend. Install it with: pip install 'antiquarian[anthropic]'"
            ) from e
        return anthropic

    def preflight(self) -> None:
        """Fail fast if the key is missing or the SDK isn't installed."""
        self._require_key()
        self._import_sdk()

    def synthesize(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout_seconds: int = 300,
        log: Callable[[str], None] = _noop,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        api_key = self._require_key()
        anthropic = self._import_sdk()
        client = anthropic.Anthropic(api_key=api_key, timeout=float(timeout_seconds))

        def _call() -> str:
            message = client.messages.create(
                model=self.model,
                max_tokens=_ANTHROPIC_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return _anthropic_text(message)

        # APIStatusError covers 429/500/503/overloaded; APIConnectionError
        # covers transport blips. Both are worth a retry; everything else
        # (auth, bad request) is permanent and propagates as BackendError.
        transient = (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        )
        # Catch the same families that are retried so an *exhausted* retry
        # surfaces as a clean BackendError, not a raw traceback. APIConnectionError
        # does not subclass APIStatusError, so it must be named explicitly.
        try:
            return _retry_with_backoff(
                _call,
                transient=transient,
                label="anthropic-sdk",
                log=log,
                sleep=sleep,
            ).strip()
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            raise BackendError(f"Anthropic API error: {e}") from e


def _anthropic_text(message) -> str:  # type: ignore[no-untyped-def]
    """Join the text blocks of an Anthropic ``Message`` into a single string."""
    parts = [
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text"
    ]
    return "".join(parts)


#: Default Ollama model — a broadly-available local general model. Override
#: with ``ANTIQUARIAN_OLLAMA_MODEL`` or the ``model`` constructor arg.
_DEFAULT_OLLAMA_MODEL = "llama3.1"


class OllamaBackend:
    """Local-model backend served by Ollama — the no-API-key path (#91).

    Talks to a local Ollama server via the official ``ollama`` package, which
    honors the ``OLLAMA_HOST`` env var for non-default hosts. The model
    defaults to ``llama3.1`` and is overridable via ``ANTIQUARIAN_OLLAMA_MODEL``
    or the ``model`` constructor arg.

    Construction is side-effect-free; the package import and a connectivity
    check happen in :meth:`preflight` / :meth:`synthesize`.
    """

    name = "ollama"

    def __init__(self, *, model: str | None = None, host: str | None = None) -> None:
        self.model = model or os.environ.get(
            "ANTIQUARIAN_OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL
        )
        # host=None lets the ollama client fall back to OLLAMA_HOST / default.
        self.host = host

    def _import_client(self):  # type: ignore[no-untyped-def]
        try:
            import ollama
        except ImportError as e:
            raise BackendError(
                "The 'ollama' package is required for the ollama backend. Install "
                "it with: pip install 'antiquarian[ollama]' (and run a local "
                "Ollama server)."
            ) from e
        return ollama

    def _client(self):  # type: ignore[no-untyped-def]
        ollama = self._import_client()
        return ollama, ollama.Client(host=self.host) if self.host else ollama.Client()

    def preflight(self) -> None:
        """Fail fast if the package is missing or the server is unreachable."""
        ollama, client = self._client()
        try:
            client.list()
        except Exception as e:  # ollama raises ConnectionError / ResponseError
            raise BackendError(
                f"Could not reach the Ollama server ({type(e).__name__}: {e}). "
                "Is it running? Start it with: ollama serve"
            ) from e

    def synthesize(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout_seconds: int = 300,
        log: Callable[[str], None] = _noop,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        ollama, client = self._client()

        def _call() -> str:
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
            )
            return response["message"]["content"]

        # Catch ConnectionError too (the retried transient) so an exhausted
        # retry surfaces as a clean BackendError rather than a raw traceback.
        try:
            return _retry_with_backoff(
                _call,
                transient=(ConnectionError,),
                label="ollama",
                log=log,
                sleep=sleep,
            ).strip()
        except (ollama.ResponseError, ConnectionError) as e:
            raise BackendError(f"Ollama error: {e}") from e


#: Default Exo model. ``llama-3.2-3b`` is small enough to run on a single
#: everyday device yet gives noticeably better narrative than the 1B variant;
#: override with ``ANTIQUARIAN_EXO_MODEL``. Model ids follow Exo's own naming
#: (e.g. ``llama-3.2-1b``, ``llama-3.1-70b``).
_DEFAULT_EXO_MODEL = "llama-3.2-3b"

#: Default Exo endpoint. Exo serves an OpenAI-compatible API at
#: ``http://localhost:52415/v1`` by default; override with
#: ``ANTIQUARIAN_EXO_BASE_URL`` to point at another node in the cluster.
_DEFAULT_EXO_BASE_URL = "http://localhost:52415/v1"

#: Exo needs no auth, but the ``openai`` client refuses an empty key. This
#: placeholder is sent and ignored by Exo; override with
#: ``ANTIQUARIAN_EXO_API_KEY`` for setups that front Exo with an authed proxy.
_DEFAULT_EXO_API_KEY = "exo"

#: Upper bound on synthesized tokens. Mirrors the Anthropic backend — a survey
#: runs ~2000 words; 8192 leaves headroom without inviting runaway output.
_EXO_MAX_TOKENS = 8192


class ExoBackend:
    """OpenAI-compatible backend for an Exo cluster — the run-it-across-your-own-devices path (#102).

    Exo (https://github.com/exo-explore/exo) exposes an OpenAI-compatible API
    (default ``http://localhost:52415/v1``), so this backend talks to it
    through the official ``openai`` SDK pointed at that base URL. Exo requires
    no auth; a placeholder key is sent because the SDK refuses an empty one.

    Everything is overridable: ``ANTIQUARIAN_EXO_MODEL`` (default
    ``llama-3.2-3b``), ``ANTIQUARIAN_EXO_BASE_URL``, and ``ANTIQUARIAN_EXO_API_KEY``
    (for a fronting proxy), or their constructor args.

    Construction is side-effect-free; the package import and a connectivity
    check happen in :meth:`preflight` / :meth:`synthesize`.
    """

    name = "exo"

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model or os.environ.get(
            "ANTIQUARIAN_EXO_MODEL", _DEFAULT_EXO_MODEL
        )
        self.base_url = base_url or os.environ.get(
            "ANTIQUARIAN_EXO_BASE_URL", _DEFAULT_EXO_BASE_URL
        )
        self.api_key = api_key or os.environ.get(
            "ANTIQUARIAN_EXO_API_KEY", _DEFAULT_EXO_API_KEY
        )

    def _import_sdk(self):  # type: ignore[no-untyped-def]
        try:
            import openai
        except ImportError as e:
            raise BackendError(
                "The 'openai' package is required for the exo backend. Install "
                "it with: pip install 'antiquarian[exo]' (and run a local Exo "
                "cluster)."
            ) from e
        return openai

    def _client(self, *, timeout_seconds: int = 300):  # type: ignore[no-untyped-def]
        openai = self._import_sdk()
        client = openai.OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=float(timeout_seconds),
        )
        return openai, client

    def preflight(self) -> None:
        """Fail fast if the package is missing or the cluster is unreachable."""
        openai, client = self._client()
        try:
            client.models.list()
        except Exception as e:  # openai raises APIConnectionError / APIStatusError
            raise BackendError(
                f"Could not reach the Exo cluster at {self.base_url} "
                f"({type(e).__name__}: {e}). Is it running? Start it with: exo"
            ) from e

    def synthesize(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout_seconds: int = 300,
        log: Callable[[str], None] = _noop,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        openai, client = self._client(timeout_seconds=timeout_seconds)

        def _call() -> str:
            completion = client.chat.completions.create(
                model=self.model,
                max_tokens=_EXO_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
            )
            return _openai_text(completion)

        # APIConnectionError covers transport blips; RateLimitError /
        # InternalServerError cover 429/500/503. All worth a retry; everything
        # else (bad request, model not loaded) is permanent.
        transient = (
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        )
        # Catch the retried families so an *exhausted* retry surfaces as a clean
        # BackendError, not a raw traceback. APIConnectionError does not subclass
        # APIStatusError, so it must be named explicitly.
        try:
            return _retry_with_backoff(
                _call,
                transient=transient,
                label="exo",
                log=log,
                sleep=sleep,
            ).strip()
        except (openai.APIStatusError, openai.APIConnectionError) as e:
            raise BackendError(f"Exo API error: {e}") from e


def _openai_text(completion) -> str:  # type: ignore[no-untyped-def]
    """Extract the assistant message text from an OpenAI ``ChatCompletion``.

    Null-safe: an empty ``choices`` list or a ``None`` content (which the API
    can return alongside a refusal or tool call) yields an empty string rather
    than raising.
    """
    if not completion.choices:
        return ""
    return completion.choices[0].message.content or ""


# Name → factory. Factories construct fresh, side-effect-free instances; the
# CLI calls ``preflight`` on the chosen one before doing any work.
_BACKENDS: dict[str, Callable[[], NarrativeBackend]] = {
    "claude-p": ClaudePBackend,
    "anthropic-sdk": AnthropicSDKBackend,
    "ollama": OllamaBackend,
    "exo": ExoBackend,
}


# The default — used by synthesize_narrative / synthesize_survey when no
# backend is passed in. A singleton is fine because the backend itself is
# stateless; injecting one is the only way to override it.
DEFAULT_BACKEND: NarrativeBackend = ClaudePBackend()
