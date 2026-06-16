"""Tests for the pluggable narrative backend interface (#30, #91)."""

from __future__ import annotations

import subprocess
import types
from unittest.mock import patch

import pytest

from antiquarian.backends import (
    DEFAULT_BACKEND,
    AnthropicSDKBackend,
    BackendError,
    ClaudePBackend,
    ExoBackend,
    NarrativeBackend,
    OllamaBackend,
    _anthropic_text,
    _openai_text,
    _retry_with_backoff,
    available_backends,
    get_backend,
    resolve_backend_name,
)


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


# --- #91: backend selection / resolution ----------------------------------


class TestResolveBackendName:
    def test_explicit_wins_over_env_and_default(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_BACKEND", "ollama")
        assert resolve_backend_name("anthropic-sdk") == "anthropic-sdk"

    def test_env_used_when_no_explicit(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_BACKEND", "ollama")
        assert resolve_backend_name(None) == "ollama"

    def test_default_when_neither_set(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTIQUARIAN_BACKEND", raising=False)
        assert resolve_backend_name(None) == "claude-p"

    def test_whitespace_explicit_treated_as_unset(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_BACKEND", "ollama")
        assert resolve_backend_name("   ") == "ollama"

    def test_whitespace_env_treated_as_unset(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_BACKEND", "   ")
        assert resolve_backend_name(None) == "claude-p"

    def test_explicit_is_stripped(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTIQUARIAN_BACKEND", raising=False)
        assert resolve_backend_name("  ollama  ") == "ollama"


class TestGetBackend:
    def test_returns_claude_p_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTIQUARIAN_BACKEND", raising=False)
        assert isinstance(get_backend(None), ClaudePBackend)

    def test_returns_anthropic_sdk(self) -> None:
        assert isinstance(get_backend("anthropic-sdk"), AnthropicSDKBackend)

    def test_returns_ollama(self) -> None:
        assert isinstance(get_backend("ollama"), OllamaBackend)

    def test_returns_exo(self) -> None:
        assert isinstance(get_backend("exo"), ExoBackend)

    def test_unknown_name_raises_backend_error(self) -> None:
        with pytest.raises(BackendError) as exc:
            get_backend("gpt-9000")
        assert "gpt-9000" in str(exc.value)
        # Error names the available options so the user can recover.
        assert "claude-p" in str(exc.value)

    def test_available_backends_lists_all_four(self) -> None:
        assert available_backends() == [
            "anthropic-sdk",
            "claude-p",
            "exo",
            "ollama",
        ]


# --- #91: shared retry helper ----------------------------------------------


class _Transient(Exception):
    pass


class _Permanent(Exception):
    pass


class TestRetryWithBackoff:
    def test_returns_on_first_success(self) -> None:
        out = _retry_with_backoff(
            lambda: "ok", transient=(_Transient,), label="t", sleep=lambda _s: None
        )
        assert out == "ok"

    def test_retries_transient_then_succeeds(self) -> None:
        calls = {"n": 0}

        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise _Transient("blip")
            return "recovered"

        out = _retry_with_backoff(
            flaky,
            transient=(_Transient,),
            label="t",
            max_attempts=3,
            sleep=lambda _s: None,
        )
        assert out == "recovered"
        assert calls["n"] == 3

    def test_gives_up_after_max_attempts(self) -> None:
        calls = {"n": 0}

        def always_fail() -> str:
            calls["n"] += 1
            raise _Transient("nope")

        with pytest.raises(_Transient):
            _retry_with_backoff(
                always_fail,
                transient=(_Transient,),
                label="t",
                max_attempts=3,
                sleep=lambda _s: None,
            )
        assert calls["n"] == 3

    def test_non_transient_propagates_immediately(self) -> None:
        calls = {"n": 0}

        def boom() -> str:
            calls["n"] += 1
            raise _Permanent("auth")

        with pytest.raises(_Permanent):
            _retry_with_backoff(
                boom, transient=(_Transient,), label="t", sleep=lambda _s: None
            )
        assert calls["n"] == 1  # never retried


# --- #91: Anthropic SDK backend --------------------------------------------


class _FakeAPIStatusError(Exception):
    pass


class _FakeAPIConnectionError(Exception):
    pass


class _FakeRateLimitError(_FakeAPIStatusError):
    pass


class _FakeInternalServerError(_FakeAPIStatusError):
    pass


def _text_message(text: str):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)]
    )


class _FakeMessages:
    def __init__(self, behavior) -> None:
        self.behavior = behavior
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.behavior(kwargs)


class _FakeAnthropicClient:
    def __init__(self, behavior) -> None:
        self.messages = _FakeMessages(behavior)


def _fake_anthropic_module(client: _FakeAnthropicClient):
    return types.SimpleNamespace(
        Anthropic=lambda **_kw: client,
        APIStatusError=_FakeAPIStatusError,
        APIConnectionError=_FakeAPIConnectionError,
        RateLimitError=_FakeRateLimitError,
        InternalServerError=_FakeInternalServerError,
    )


class TestAnthropicSDKBackendConfig:
    def test_reads_key_from_arg(self) -> None:
        b = AnthropicSDKBackend(api_key="sk-arg")
        assert b.api_key == "sk-arg"

    def test_reads_key_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
        assert AnthropicSDKBackend().api_key == "sk-env"

    def test_model_defaults(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTIQUARIAN_ANTHROPIC_MODEL", raising=False)
        assert AnthropicSDKBackend().model == "claude-sonnet-4-6"

    def test_model_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_ANTHROPIC_MODEL", "claude-opus-4-8")
        assert AnthropicSDKBackend().model == "claude-opus-4-8"

    def test_missing_key_raises_on_synthesize(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(BackendError) as exc:
            AnthropicSDKBackend().synthesize("S", "U", sleep=lambda _s: None)
        assert "ANTHROPIC_API_KEY" in str(exc.value)


class TestAnthropicSDKBackendSynthesize:
    def test_happy_path_passes_prompts_and_returns_text(self) -> None:
        client = _FakeAnthropicClient(lambda _kw: _text_message("  the narrative \n"))
        backend = AnthropicSDKBackend(api_key="sk", model="claude-sonnet-4-6")
        backend._import_sdk = lambda: _fake_anthropic_module(client)

        out = backend.synthesize("SYSTEM", "USER", sleep=lambda _s: None)

        assert out == "the narrative"
        sent = client.messages.calls[0]
        assert sent["model"] == "claude-sonnet-4-6"
        assert sent["system"] == "SYSTEM"
        assert sent["messages"] == [{"role": "user", "content": "USER"}]

    def test_retries_transient_then_succeeds(self) -> None:
        state = {"n": 0}

        def behavior(_kw):
            state["n"] += 1
            if state["n"] == 1:
                raise _FakeAPIConnectionError("blip")
            return _text_message("recovered")

        client = _FakeAnthropicClient(behavior)
        backend = AnthropicSDKBackend(api_key="sk")
        backend._import_sdk = lambda: _fake_anthropic_module(client)

        out = backend.synthesize("S", "U", sleep=lambda _s: None)
        assert out == "recovered"
        assert state["n"] == 2

    def test_api_status_error_becomes_backend_error(self) -> None:
        def behavior(_kw):
            raise _FakeAPIStatusError("400 bad request")

        client = _FakeAnthropicClient(behavior)
        backend = AnthropicSDKBackend(api_key="sk")
        backend._import_sdk = lambda: _fake_anthropic_module(client)

        with pytest.raises(BackendError) as exc:
            backend.synthesize("S", "U", sleep=lambda _s: None)
        assert "Anthropic API error" in str(exc.value)

    def test_exhausted_connection_error_becomes_backend_error(self) -> None:
        """A transient that never recovers must surface cleanly, not as a traceback.

        APIConnectionError does not subclass APIStatusError, so it would escape
        the wrapper if only APIStatusError were caught.
        """

        def behavior(_kw):
            raise _FakeAPIConnectionError("connection reset")

        client = _FakeAnthropicClient(behavior)
        backend = AnthropicSDKBackend(api_key="sk")
        backend._import_sdk = lambda: _fake_anthropic_module(client)

        with pytest.raises(BackendError):
            backend.synthesize("S", "U", sleep=lambda _s: None)

    def test_satisfies_protocol(self) -> None:
        assert isinstance(AnthropicSDKBackend(api_key="sk"), NarrativeBackend)


class TestAnthropicText:
    def test_joins_text_blocks_only(self) -> None:
        msg = types.SimpleNamespace(
            content=[
                types.SimpleNamespace(type="text", text="hello "),
                types.SimpleNamespace(type="tool_use", text="ignored"),
                types.SimpleNamespace(type="text", text="world"),
            ]
        )
        assert _anthropic_text(msg) == "hello world"


# --- #91: Ollama backend ---------------------------------------------------


class _FakeResponseError(Exception):
    pass


class _FakeOllamaClient:
    def __init__(self, chat_behavior=None, list_behavior=None) -> None:
        self._chat = chat_behavior
        self._list = list_behavior
        self.chat_calls: list[dict] = []

    def chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        return self._chat(kwargs)

    def list(self):
        if self._list is not None:
            return self._list()
        return {"models": []}


def _fake_ollama_module():
    return types.SimpleNamespace(ResponseError=_FakeResponseError)


class TestOllamaBackendConfig:
    def test_model_defaults(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTIQUARIAN_OLLAMA_MODEL", raising=False)
        assert OllamaBackend().model == "llama3.1"

    def test_model_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_OLLAMA_MODEL", "mistral")
        assert OllamaBackend().model == "mistral"


class TestOllamaBackendSynthesize:
    def test_happy_path_passes_prompts_and_returns_text(self) -> None:
        client = _FakeOllamaClient(
            chat_behavior=lambda _kw: {"message": {"content": " local out \n"}}
        )
        backend = OllamaBackend(model="llama3.1")
        backend._client = lambda: (_fake_ollama_module(), client)

        out = backend.synthesize("SYSTEM", "USER", sleep=lambda _s: None)

        assert out == "local out"
        sent = client.chat_calls[0]
        assert sent["model"] == "llama3.1"
        assert sent["messages"] == [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "USER"},
        ]
        assert sent["stream"] is False

    def test_response_error_becomes_backend_error(self) -> None:
        def chat(_kw):
            raise _FakeResponseError("model not found")

        client = _FakeOllamaClient(chat_behavior=chat)
        backend = OllamaBackend()
        backend._client = lambda: (_fake_ollama_module(), client)

        with pytest.raises(BackendError) as exc:
            backend.synthesize("S", "U", sleep=lambda _s: None)
        assert "Ollama error" in str(exc.value)

    def test_exhausted_connection_error_becomes_backend_error(self) -> None:
        """A never-recovering ConnectionError must surface cleanly, not as a traceback."""

        def chat(_kw):
            raise ConnectionError("refused")

        client = _FakeOllamaClient(chat_behavior=chat)
        backend = OllamaBackend()
        backend._client = lambda: (_fake_ollama_module(), client)

        with pytest.raises(BackendError):
            backend.synthesize("S", "U", sleep=lambda _s: None)

    def test_preflight_unreachable_becomes_backend_error(self) -> None:
        def boom():
            raise ConnectionError("refused")

        client = _FakeOllamaClient(list_behavior=boom)
        backend = OllamaBackend()
        backend._client = lambda: (_fake_ollama_module(), client)

        with pytest.raises(BackendError) as exc:
            backend.preflight()
        assert "Ollama" in str(exc.value)

    def test_preflight_reachable_passes(self) -> None:
        client = _FakeOllamaClient(list_behavior=lambda: {"models": []})
        backend = OllamaBackend()
        backend._client = lambda: (_fake_ollama_module(), client)
        backend.preflight()  # should not raise

    def test_satisfies_protocol(self) -> None:
        assert isinstance(OllamaBackend(), NarrativeBackend)


# --- #102: Exo backend (OpenAI-compatible local cluster) -------------------


class _FakeOpenAIAPIStatusError(Exception):
    pass


class _FakeOpenAIAPIConnectionError(Exception):
    pass


class _FakeOpenAIRateLimitError(_FakeOpenAIAPIStatusError):
    pass


class _FakeOpenAIInternalServerError(_FakeOpenAIAPIStatusError):
    pass


def _chat_completion(text: str):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))]
    )


class _FakeCompletions:
    def __init__(self, behavior) -> None:
        self.behavior = behavior
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.behavior(kwargs)


class _FakeModels:
    def __init__(self, list_behavior=None) -> None:
        self._list = list_behavior

    def list(self):
        if self._list is not None:
            return self._list()
        return types.SimpleNamespace(data=[])


class _FakeOpenAIClient:
    def __init__(self, chat_behavior=None, list_behavior=None) -> None:
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(chat_behavior))
        self.models = _FakeModels(list_behavior)
        self.init_kwargs: dict = {}


def _fake_openai_module(client: _FakeOpenAIClient):
    def _make(**kwargs):
        client.init_kwargs = kwargs
        return client

    return types.SimpleNamespace(
        OpenAI=_make,
        APIStatusError=_FakeOpenAIAPIStatusError,
        APIConnectionError=_FakeOpenAIAPIConnectionError,
        RateLimitError=_FakeOpenAIRateLimitError,
        InternalServerError=_FakeOpenAIInternalServerError,
    )


class TestExoBackendConfig:
    def test_model_defaults(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTIQUARIAN_EXO_MODEL", raising=False)
        assert ExoBackend().model == "llama-3.2-3b"

    def test_model_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_EXO_MODEL", "llama-3.1-70b")
        assert ExoBackend().model == "llama-3.1-70b"

    def test_base_url_defaults(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTIQUARIAN_EXO_BASE_URL", raising=False)
        assert ExoBackend().base_url == "http://localhost:52415/v1"

    def test_base_url_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_EXO_BASE_URL", "http://box.local:9000/v1")
        assert ExoBackend().base_url == "http://box.local:9000/v1"

    def test_api_key_placeholder_when_unset(self, monkeypatch) -> None:
        """Exo needs no auth, but the openai client requires a non-empty key."""
        monkeypatch.delenv("ANTIQUARIAN_EXO_API_KEY", raising=False)
        assert ExoBackend().api_key == "exo"

    def test_api_key_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTIQUARIAN_EXO_API_KEY", "proxy-token")
        assert ExoBackend().api_key == "proxy-token"


class TestExoBackendSynthesize:
    def test_happy_path_passes_prompts_and_returns_text(self) -> None:
        client = _FakeOpenAIClient(
            chat_behavior=lambda _kw: _chat_completion(" cluster out \n")
        )
        backend = ExoBackend(model="llama-3.2-3b")
        backend._import_sdk = lambda: _fake_openai_module(client)

        out = backend.synthesize("SYSTEM", "USER", sleep=lambda _s: None)

        assert out == "cluster out"
        sent = client.chat.completions.calls[0]
        assert sent["model"] == "llama-3.2-3b"
        assert sent["messages"] == [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "USER"},
        ]

    def test_client_built_with_base_url_and_key(self) -> None:
        client = _FakeOpenAIClient(chat_behavior=lambda _kw: _chat_completion("ok"))
        backend = ExoBackend(base_url="http://h:1/v1", api_key="k")
        backend._import_sdk = lambda: _fake_openai_module(client)

        backend.synthesize("S", "U", timeout_seconds=42, sleep=lambda _s: None)

        assert client.init_kwargs["base_url"] == "http://h:1/v1"
        assert client.init_kwargs["api_key"] == "k"
        assert client.init_kwargs["timeout"] == 42.0

    def test_retries_transient_then_succeeds(self) -> None:
        state = {"n": 0}

        def behavior(_kw):
            state["n"] += 1
            if state["n"] == 1:
                raise _FakeOpenAIAPIConnectionError("blip")
            return _chat_completion("recovered")

        client = _FakeOpenAIClient(chat_behavior=behavior)
        backend = ExoBackend()
        backend._import_sdk = lambda: _fake_openai_module(client)

        out = backend.synthesize("S", "U", sleep=lambda _s: None)
        assert out == "recovered"
        assert state["n"] == 2

    def test_api_status_error_becomes_backend_error(self) -> None:
        def behavior(_kw):
            raise _FakeOpenAIAPIStatusError("404 model not loaded")

        client = _FakeOpenAIClient(chat_behavior=behavior)
        backend = ExoBackend()
        backend._import_sdk = lambda: _fake_openai_module(client)

        with pytest.raises(BackendError) as exc:
            backend.synthesize("S", "U", sleep=lambda _s: None)
        assert "Exo API error" in str(exc.value)

    def test_exhausted_connection_error_becomes_backend_error(self) -> None:
        """APIConnectionError does not subclass APIStatusError, so it must be
        caught explicitly or it escapes the wrapper as a raw traceback."""

        def behavior(_kw):
            raise _FakeOpenAIAPIConnectionError("connection refused")

        client = _FakeOpenAIClient(chat_behavior=behavior)
        backend = ExoBackend()
        backend._import_sdk = lambda: _fake_openai_module(client)

        with pytest.raises(BackendError):
            backend.synthesize("S", "U", sleep=lambda _s: None)

    def test_preflight_unreachable_becomes_backend_error(self) -> None:
        def boom():
            raise _FakeOpenAIAPIConnectionError("refused")

        client = _FakeOpenAIClient(list_behavior=boom)
        backend = ExoBackend()
        backend._import_sdk = lambda: _fake_openai_module(client)

        with pytest.raises(BackendError) as exc:
            backend.preflight()
        assert "Exo" in str(exc.value)

    def test_preflight_reachable_passes(self) -> None:
        client = _FakeOpenAIClient(list_behavior=lambda: types.SimpleNamespace(data=[]))
        backend = ExoBackend()
        backend._import_sdk = lambda: _fake_openai_module(client)
        backend.preflight()  # should not raise

    def test_satisfies_protocol(self) -> None:
        assert isinstance(ExoBackend(), NarrativeBackend)


class TestOpenAIText:
    def test_extracts_first_choice_content(self) -> None:
        assert _openai_text(_chat_completion("hello world")) == "hello world"

    def test_empty_choices_returns_empty_string(self) -> None:
        msg = types.SimpleNamespace(choices=[])
        assert _openai_text(msg) == ""

    def test_none_content_returns_empty_string(self) -> None:
        msg = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=None))]
        )
        assert _openai_text(msg) == ""
