# Julia Agent Safety Classifier + DeepSeek Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pre-screen every prompt fed to the julia/autopep agent with `openai/gpt-oss-safeguard-20b` via OpenRouter; when flagged harmful, swap the run's underlying model from `gpt-5.5` to `deepseek/deepseek-v4-pro` pinned to the Together inference provider — without changing tools, sandbox capabilities, session persistence, or streaming.

**Architecture:**
1. **Single integration point.** Only `autopep_agent/runner.py::execute_run` learns about safety. It calls a new `safety.classify_prompt(...)` after `get_run_context` and before `build_autopep_agent`. The verdict picks which `RunConfig.model` to pass.
2. **Stay inside the SDK contract.** `RunConfig.model` accepts both `str` and a `Model` instance. The safe path keeps today's `gpt-5.5` string (zero behavioral change). The harmful path passes `OpenAIChatCompletionsModel(model="deepseek/deepseek-v4-pro", openai_client=AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY))` plus `model_settings=ModelSettings(extra_args={"provider": {"only": ["together"], "allow_fallbacks": False}})`. Sandbox capabilities (Shell / Filesystem / Compaction) and tool calling are model-agnostic and continue to work.
3. **Fail-open on classifier errors.** Classifier timeouts / non-JSON / OpenRouter outages return `verdict=safe` with `rationale=classifier_error` and emit a ledger warning. Rationale: today, an unsafe prompt to `gpt-5.5` already surfaces as the existing `OPENAI_PROMPT_BLOCKED_REASON` failure path — failing open preserves status quo on classifier downtime instead of degrading every run to DeepSeek.

**Tech Stack:** Python 3.12, `openai-agents[modal]` (>= the version that exposes `ModelSettings.extra_args`), `openai` AsyncOpenAI, `httpx`, `pytest`. Modal Secret `autopep-runtime` for `OPENROUTER_API_KEY`. No frontend changes required (a new ledger event type is added but the UI ignores unknown types today).

**Out of scope (do not touch):**
- Smoke runs (`smoke_chat`/`smoke_tool`/`smoke_sandbox`) — they bypass the classifier.
- The OpenAI prompt-block error fallback in `_append_failure_event` — it still fires when DeepSeek itself rejects.
- Tool implementations, R2 mount, session, streaming coalescer, attachment download.
- Frontend; we only add a new ledger event type that the existing renderer skips silently.

---

## Background research notes

(For the implementing engineer — keep handy while reading the SDK source.)

- **Agents SDK custom provider docs:** https://openai.github.io/openai-agents-python/models/ — the canonical pattern is `OpenAIChatCompletionsModel(model="...", openai_client=AsyncOpenAI(base_url=..., api_key=...))`. We use `OpenAIChatCompletionsModel` (not `OpenAIResponsesModel`) because OpenRouter does not implement the Responses API — only chat completions.
- **`RunConfig.model` accepts `str | Model | None`** — confirmed in `agents/run.py` source. Passing a `Model` instance is the documented per-run override.
- **`ModelSettings.extra_args`** — confirmed in SDK docs as the documented passthrough for provider-specific request body fields (e.g. OpenRouter's `provider` object). It rides along with the chat completions request body.
- **OpenRouter provider routing:** docs at https://openrouter.ai/docs/features/provider-routing. `provider.only=["together"]` + `provider.allow_fallbacks=false` forces the Together inference provider and refuses silent fallback to a different provider (which would defeat the point of the override).
- **Classifier model id:** `openai/gpt-oss-safeguard-20b` on OpenRouter — a 20B safety classifier. Use `response_format={"type": "json_schema", ...}` for structured output so we don't have to tolerate free-text drift.
- **Modal Secret rotation:** `autopep-runtime` is mounted by `autopep_worker.run_autopep_agent` (autopep/modal/autopep_worker.py:38). Adding a key to that secret makes it available as `os.environ["OPENROUTER_API_KEY"]` inside the Modal function.

### Confirmed: SDK is compatible with sandbox + non-OpenAI provider

The runner today calls `Runner.run_streamed(agent, ..., run_config=run_config)` where `agent` is a `SandboxAgent` with `tools=[...]` and `capabilities=[Shell, Filesystem, Compaction, Skills]`. The sandbox layer is a separate construct (`SandboxRunConfig` with `ModalSandboxClient`) that only governs how *sandbox tool calls* dispatch — it doesn't constrain the LLM. The model is selected per-run via `RunConfig.model`. So switching the model has **no effect** on Shell / Filesystem / Compaction / R2Mount / Skills, and tool dispatch continues through the SDK's tool-call machinery (which works for both Responses and Chat Completions backends).

The only model-shape risk is parallel tool calls. Chat-completions-style providers tend to emit one tool call at a time vs. Responses' parallel tool calls; the agent already calls multiple tools sequentially in its typical loop, so this is acceptable.

---

## Bite-sized tasks

### Task 1: Add `OPENROUTER_API_KEY` to `WorkerConfig`

**Files:**
- Modify: [autopep/modal/autopep_agent/config.py](autopep/modal/autopep_agent/config.py)
- Modify: [autopep/modal/tests/test_config.py](autopep/modal/tests/test_config.py)

**Step 1: Add a failing test for the new required env var**

In `autopep/modal/tests/test_config.py`, extend `REQUIRED_ENV` and add an assertion:

```python
REQUIRED_ENV = {
    # ... existing keys ...
    "OPENAI_API_KEY": "openai-key",
    "OPENROUTER_API_KEY": "openrouter-key",
}
```

Add to `test_from_env_reads_required_values_and_normalizes_urls`:

```python
    assert config.openrouter_api_key == REQUIRED_ENV["OPENROUTER_API_KEY"]
```

Add a new test:

```python
def test_from_env_requires_openrouter_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY")

    with pytest.raises(RuntimeError) as exc_info:
        WorkerConfig.from_env()

    assert "OPENROUTER_API_KEY" in str(exc_info.value)
```

**Step 2: Run tests to verify failure**

Run: `cd autopep/modal && pytest tests/test_config.py -v`
Expected: FAIL — `WorkerConfig` has no `openrouter_api_key` field; missing-env test would also fail because the var isn't required yet.

**Step 3: Implement in `config.py`**

Add `"OPENROUTER_API_KEY"` to `REQUIRED_ENV_VARS`, add `openrouter_api_key: str` to the `WorkerConfig` dataclass, populate it in `from_env`:

```python
REQUIRED_ENV_VARS = (
    # ... existing ...
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)
```

```python
@dataclass(frozen=True)
class WorkerConfig:
    # ... existing fields ...
    openai_api_key: str
    openrouter_api_key: str
    default_model: str
```

In `from_env`, add:

```python
            openrouter_api_key=values["OPENROUTER_API_KEY"],
```

Update the test config helper in `tests/test_runner.py` (`_test_config()`) and the `REQUIRED_RUNTIME_ENV` dict to include `openrouter_api_key="openrouter-test"` and `"OPENROUTER_API_KEY": "openrouter-test"`. Also update `tests/test_smoke_runner.py` and `tests/test_mvp_persistence.py` env dicts.

**Step 4: Run tests to verify pass**

Run: `cd autopep/modal && pytest tests/test_config.py tests/test_runner.py tests/test_smoke_runner.py tests/test_mvp_persistence.py -v`
Expected: PASS for all.

**Step 5: Commit**

```bash
git add autopep/modal/autopep_agent/config.py autopep/modal/tests/test_config.py autopep/modal/tests/test_runner.py autopep/modal/tests/test_smoke_runner.py autopep/modal/tests/test_mvp_persistence.py
git commit -m "feat(autopep): require OPENROUTER_API_KEY in WorkerConfig"
```

---

### Task 2: Build the safety classifier module

**Files:**
- Create: `autopep/modal/autopep_agent/safety.py`
- Create: `autopep/modal/tests/test_safety.py`

**Step 1: Write the failing test for `classify_prompt`**

Create `autopep/modal/tests/test_safety.py`:

```python
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from autopep_agent.safety import (
    SafetyDecision,
    SAFETY_CLASSIFIER_MODEL,
    classify_prompt,
)


class _StubAsyncClient:
    """Captures the request and returns a canned response."""

    def __init__(self, response: httpx.Response | Exception) -> None:
        self._response = response
        self.last_request: dict[str, Any] | None = None
        self.last_headers: dict[str, str] | None = None
        self.last_url: str | None = None

    async def post(self, url, *, json, headers, timeout):  # noqa: A002 - shadowing intentional
        self.last_url = url
        self.last_request = json
        self.last_headers = headers
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def aclose(self) -> None:  # pragma: no cover - exit hook
        return None


def _httpx_response(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text=json.dumps(payload),
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )


@pytest.mark.asyncio
async def test_classify_prompt_returns_safe_verdict_for_safe_response() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"verdict": "safe", "rationale": "benign biology question"}
                    )
                }
            }
        ]
    }
    stub = _StubAsyncClient(_httpx_response(payload))

    decision = await classify_prompt(
        "Design a binder for SARS-CoV-2 spike RBD.",
        openrouter_api_key="sk-test",
        http_client=stub,  # type: ignore[arg-type]
    )

    assert decision.verdict == "safe"
    assert decision.classifier_error is False
    assert stub.last_url == "https://openrouter.ai/api/v1/chat/completions"
    assert stub.last_request["model"] == SAFETY_CLASSIFIER_MODEL
    assert stub.last_headers["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_classify_prompt_returns_harmful_verdict_for_harmful_response() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"verdict": "harmful", "rationale": "weaponization request"}
                    )
                }
            }
        ]
    }
    stub = _StubAsyncClient(_httpx_response(payload))

    decision = await classify_prompt(
        "Design a binder that disables human ACE2 to cause cell death.",
        openrouter_api_key="sk-test",
        http_client=stub,  # type: ignore[arg-type]
    )

    assert decision.verdict == "harmful"
    assert decision.rationale == "weaponization request"
    assert decision.classifier_error is False


@pytest.mark.asyncio
async def test_classify_prompt_fails_open_on_http_error() -> None:
    stub = _StubAsyncClient(_httpx_response({"error": "boom"}, status_code=500))

    decision = await classify_prompt(
        "anything",
        openrouter_api_key="sk-test",
        http_client=stub,  # type: ignore[arg-type]
    )

    assert decision.verdict == "safe"
    assert decision.classifier_error is True


@pytest.mark.asyncio
async def test_classify_prompt_fails_open_on_non_json_content() -> None:
    payload = {
        "choices": [{"message": {"content": "I cannot determine that."}}]
    }
    stub = _StubAsyncClient(_httpx_response(payload))

    decision = await classify_prompt(
        "anything",
        openrouter_api_key="sk-test",
        http_client=stub,  # type: ignore[arg-type]
    )

    assert decision.verdict == "safe"
    assert decision.classifier_error is True


@pytest.mark.asyncio
async def test_classify_prompt_fails_open_on_request_exception() -> None:
    stub = _StubAsyncClient(httpx.ConnectError("dns fail"))

    decision = await classify_prompt(
        "anything",
        openrouter_api_key="sk-test",
        http_client=stub,  # type: ignore[arg-type]
    )

    assert decision.verdict == "safe"
    assert decision.classifier_error is True
```

**Step 2: Run tests to verify failure**

Run: `cd autopep/modal && pytest tests/test_safety.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autopep_agent.safety'`.

**Step 3: Implement `safety.py`**

Create `autopep/modal/autopep_agent/safety.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx


SAFETY_CLASSIFIER_MODEL = "openai/gpt-oss-safeguard-20b"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_CLASSIFIER_TIMEOUT_S = 10.0

_SYSTEM_PROMPT = (
    "You are a safety classifier for an automated protein-binder design agent. "
    "Decide whether the user prompt is safe to send to a frontier LLM, or whether "
    "the prompt is reasonably likely to trigger a refusal because it requests "
    "biological-weapon design, malicious dual-use uplift (toxin/pathogen "
    "enhancement, gain-of-function targeting humans, evasion of biosecurity "
    "screening), or other harmful content. Reply ONLY with JSON matching the "
    'schema {"verdict": "safe" | "harmful", "rationale": "<short reason>"}.'
)


@dataclass(frozen=True)
class SafetyDecision:
    """Result of running gpt-oss-safeguard on a user prompt.

    ``classifier_error=True`` means the classifier itself failed (timeout,
    non-JSON content, HTTP 5xx) and the verdict was forced to ``"safe"`` to
    fail open. The runner emits a warning ledger event in that case.
    """

    verdict: Literal["safe", "harmful"]
    rationale: str
    classifier_error: bool
    raw_status_code: int | None = None


class _PostClient(Protocol):
    async def post(
        self,
        url: str,
        *,
        json: Any,
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        ...


def _safe_decision(rationale: str, *, status_code: int | None = None) -> SafetyDecision:
    return SafetyDecision(
        verdict="safe",
        rationale=rationale,
        classifier_error=True,
        raw_status_code=status_code,
    )


def _parse_classifier_payload(
    response_json: dict[str, Any],
) -> SafetyDecision | None:
    """Return a SafetyDecision parsed from a successful 200 response, else None.

    Returns None when the JSON shape is unexpected — caller treats that as a
    classifier error and falls back to ``_safe_decision``.
    """
    try:
        choices = response_json["choices"]
        message = choices[0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError):
        return None

    if not isinstance(content, str):
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None

    verdict = payload.get("verdict")
    rationale = payload.get("rationale", "")
    if verdict not in ("safe", "harmful"):
        return None

    return SafetyDecision(
        verdict=verdict,
        rationale=str(rationale),
        classifier_error=False,
    )


async def classify_prompt(
    prompt: str,
    *,
    openrouter_api_key: str,
    http_client: _PostClient | None = None,
    timeout_s: float = DEFAULT_CLASSIFIER_TIMEOUT_S,
) -> SafetyDecision:
    """Classify ``prompt`` as ``safe`` or ``harmful`` via gpt-oss-safeguard-20b.

    Failures (non-200, non-JSON content, network exceptions) return a
    ``SafetyDecision(verdict="safe", classifier_error=True)``. The caller
    surfaces ``classifier_error`` to the ledger so operators can spot
    classifier outages without blocking users.
    """

    body = {
        "model": SAFETY_CLASSIFIER_MODEL,
        "temperature": 0.0,
        "max_tokens": 200,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "safety_decision",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["verdict", "rationale"],
                    "properties": {
                        "verdict": {"type": "string", "enum": ["safe", "harmful"]},
                        "rationale": {"type": "string"},
                    },
                },
            },
        },
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "autopep-safety-classifier",
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient()
    try:
        try:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                json=body,
                headers=headers,
                timeout=timeout_s,
            )
        except (httpx.HTTPError, OSError) as exc:
            return _safe_decision(f"classifier_request_error: {type(exc).__name__}")

        if response.status_code != 200:
            return _safe_decision(
                "classifier_http_error",
                status_code=response.status_code,
            )

        try:
            response_json = response.json()
        except ValueError:
            return _safe_decision(
                "classifier_invalid_json",
                status_code=response.status_code,
            )

        parsed = _parse_classifier_payload(response_json)
        if parsed is None:
            return _safe_decision(
                "classifier_unexpected_shape",
                status_code=response.status_code,
            )
        return parsed
    finally:
        if owns_client:
            await client.aclose()  # type: ignore[union-attr]
```

**Step 4: Run tests to verify pass**

Run: `cd autopep/modal && pytest tests/test_safety.py -v`
Expected: PASS for all 5 tests.

**Step 5: Commit**

```bash
git add autopep/modal/autopep_agent/safety.py autopep/modal/tests/test_safety.py
git commit -m "feat(autopep): gpt-oss-safeguard-20b prompt classifier (fail-open)"
```

---

### Task 3: Build the DeepSeek + Together fallback model factory

**Files:**
- Create: `autopep/modal/autopep_agent/models.py`
- Create: `autopep/modal/tests/test_models.py`

**Step 1: Write the failing test**

Create `autopep/modal/tests/test_models.py`:

```python
from __future__ import annotations

from agents import ModelSettings, OpenAIChatCompletionsModel

from autopep_agent.models import (
    FALLBACK_MODEL_ID,
    OPENROUTER_BASE_URL,
    TOGETHER_PROVIDER_SLUG,
    build_fallback_model,
    build_fallback_model_settings,
)


def test_build_fallback_model_returns_chat_completions_model_for_openrouter() -> None:
    model = build_fallback_model(openrouter_api_key="sk-test")

    assert isinstance(model, OpenAIChatCompletionsModel)
    assert model.model == FALLBACK_MODEL_ID
    # The wrapped AsyncOpenAI client must point at OpenRouter's base URL
    # so the request lands on OpenRouter and not api.openai.com.
    assert str(model._client.base_url).rstrip("/") == OPENROUTER_BASE_URL


def test_build_fallback_model_settings_pins_together_provider_no_fallback() -> None:
    settings = build_fallback_model_settings()

    assert isinstance(settings, ModelSettings)
    extra = settings.extra_args or {}
    assert extra["provider"]["only"] == [TOGETHER_PROVIDER_SLUG]
    # allow_fallbacks=False prevents OpenRouter from silently routing to a
    # non-Together backend (which would defeat the override).
    assert extra["provider"]["allow_fallbacks"] is False
```

> Note: `model._client.base_url` and `model.model` are private but stable in the SDK. If a future SDK version renames them, switch to a public surface (e.g., `model.openai_client.base_url`) — the value being asserted is what matters.

**Step 2: Run tests to verify failure**

Run: `cd autopep/modal && pytest tests/test_models.py -v`
Expected: FAIL — `autopep_agent.models` does not exist.

**Step 3: Implement `models.py`**

Create `autopep/modal/autopep_agent/models.py`:

```python
from __future__ import annotations

from agents import ModelSettings, OpenAIChatCompletionsModel
from openai import AsyncOpenAI


FALLBACK_MODEL_ID = "deepseek/deepseek-v4-pro"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TOGETHER_PROVIDER_SLUG = "together"


def build_fallback_model(*, openrouter_api_key: str) -> OpenAIChatCompletionsModel:
    """Build the DeepSeek-v4-pro model wrapped in an OpenRouter client.

    OpenRouter exposes an OpenAI-compatible chat completions endpoint, so we
    wrap an ``AsyncOpenAI`` instance pointing at OpenRouter and let the SDK's
    ``OpenAIChatCompletionsModel`` adapter handle request shaping. We pick
    ChatCompletions (not Responses) because OpenRouter does not implement
    OpenAI's Responses API.
    """

    client = AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=openrouter_api_key,
        default_headers={"X-OpenRouter-Title": "autopep-deepseek-fallback"},
    )
    return OpenAIChatCompletionsModel(model=FALLBACK_MODEL_ID, openai_client=client)


def build_fallback_model_settings() -> ModelSettings:
    """Pin the request to the Together inference provider via OpenRouter's `provider` body field.

    ``allow_fallbacks=False`` matters: without it, OpenRouter is allowed to
    silently route to a different provider when Together is congested,
    which defeats the purpose of an explicit override. We choose to fail
    the request instead — the ledger records the failure and the run
    surfaces a normal ``run_failed``.
    """

    return ModelSettings(
        extra_args={
            "provider": {
                "only": [TOGETHER_PROVIDER_SLUG],
                "allow_fallbacks": False,
            },
        },
    )
```

**Step 4: Run tests to verify pass**

Run: `cd autopep/modal && pytest tests/test_models.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add autopep/modal/autopep_agent/models.py autopep/modal/tests/test_models.py
git commit -m "feat(autopep): deepseek-v4-pro fallback model factory pinned to Together"
```

---

### Task 4: Wire classifier + model swap into `runner.execute_run`

**Files:**
- Modify: [autopep/modal/autopep_agent/runner.py](autopep/modal/autopep_agent/runner.py)
- Modify: [autopep/modal/tests/test_runner.py](autopep/modal/tests/test_runner.py)

**Step 1: Write the failing tests**

Add to `autopep/modal/tests/test_runner.py` (use the existing test patterns; assume the file already imports `pytest`, `runner_mod`, `MagicMock`, `SimpleNamespace`):

```python
from autopep_agent.safety import SafetyDecision


def _patch_runner_io(monkeypatch: pytest.MonkeyPatch, *, prompt: str, captured: dict) -> None:
    """Patch the I/O dependencies of execute_run so we can drive its model selection.

    We're not testing the SDK or the DB — we're testing that execute_run
    picks the right RunConfig.model based on the classifier verdict.
    Captures the RunConfig built for the agent run on the captured dict.
    """

    async def fake_claim_run(_db_url, *, run_id):
        return True

    async def fake_get_run_context(_db_url, *, run_id, thread_id, workspace_id):
        return SimpleNamespace(
            prompt=prompt,
            model=None,  # Force default-model path.
            task_kind="chat",
            enabled_recipes=[],
        )

    async def fake_get_run_attachments(_db_url, *, run_id):
        return []

    async def fake_download(_attachments, *, workspace_id, config):
        return []

    async def fake_mark_completed(_db_url, _run_id):
        return None

    async def fake_run_streamed(*args, **kwargs):
        captured["run_config"] = kwargs.get("run_config")
        captured["agent"] = args[0] if args else kwargs.get("starting_agent")
        return SimpleNamespace(stream_events=lambda: iter([]))

    class FakeWriter:
        async def append_event(self, *args, **kwargs):
            captured.setdefault("events", []).append(kwargs)

    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "get_run_context", fake_get_run_context)
    monkeypatch.setattr(runner_mod, "get_run_attachments", fake_get_run_attachments)
    monkeypatch.setattr(
        runner_mod, "_download_attachments_to_inputs", fake_download
    )
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)
    monkeypatch.setattr(runner_mod, "EventWriter", lambda _db: FakeWriter())
    monkeypatch.setattr(runner_mod, "WorkerConfig", _MockWorkerConfig)
    monkeypatch.setattr(
        runner_mod.Runner, "run_streamed", staticmethod(fake_run_streamed)
    )


class _MockWorkerConfig:
    @classmethod
    def from_env(cls):
        return _test_config()  # already exists in this file


@pytest.mark.asyncio
async def test_execute_run_passes_default_model_string_for_safe_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    _patch_runner_io(monkeypatch, prompt="benign question", captured=captured)

    async def fake_classify(_prompt, **_kwargs):
        return SafetyDecision(verdict="safe", rationale="ok", classifier_error=False)

    monkeypatch.setattr(runner_mod, "classify_prompt", fake_classify)

    await runner_mod.execute_run(
        run_id="00000000-0000-0000-0000-000000000010",
        thread_id="00000000-0000-0000-0000-000000000011",
        workspace_id="00000000-0000-0000-0000-000000000012",
    )

    run_config = captured["run_config"]
    # Safe path: model stays a plain string equal to the WorkerConfig default.
    assert isinstance(run_config.model, str)
    assert run_config.model == _test_config().default_model
    # No model_settings override on the safe path — RunConfig.model_settings
    # is left as the SDK default (None) so the agent's own settings apply.
    assert run_config.model_settings is None


@pytest.mark.asyncio
async def test_execute_run_swaps_to_deepseek_for_harmful_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import OpenAIChatCompletionsModel

    captured: dict = {}
    _patch_runner_io(monkeypatch, prompt="harmful prompt", captured=captured)

    async def fake_classify(_prompt, **_kwargs):
        return SafetyDecision(
            verdict="harmful", rationale="weaponization", classifier_error=False
        )

    monkeypatch.setattr(runner_mod, "classify_prompt", fake_classify)

    await runner_mod.execute_run(
        run_id="00000000-0000-0000-0000-000000000020",
        thread_id="00000000-0000-0000-0000-000000000021",
        workspace_id="00000000-0000-0000-0000-000000000022",
    )

    run_config = captured["run_config"]
    assert isinstance(run_config.model, OpenAIChatCompletionsModel)
    assert run_config.model.model == "deepseek/deepseek-v4-pro"
    extra = (run_config.model_settings.extra_args or {})
    assert extra["provider"]["only"] == ["together"]
    assert extra["provider"]["allow_fallbacks"] is False

    # A safety_classified ledger event was emitted with the harmful verdict.
    safety_events = [
        e for e in captured["events"]
        if e.get("event_type") == "safety_classified"
    ]
    assert len(safety_events) == 1
    assert safety_events[0]["display"]["verdict"] == "harmful"
    assert safety_events[0]["display"]["modelUsed"] == "deepseek/deepseek-v4-pro"


@pytest.mark.asyncio
async def test_execute_run_skips_classifier_for_smoke_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke runs must not invoke the classifier.

    Smoke runs already exercise model dispatch directly via _execute_smoke_run
    — adding a classifier hop would slow them down and is unnecessary because
    smoke prompts are hard-coded test strings.
    """
    captured: dict = {"classifier_called": False}

    async def fake_classify(_prompt, **_kwargs):
        captured["classifier_called"] = True
        return SafetyDecision(verdict="safe", rationale="", classifier_error=False)

    monkeypatch.setattr(runner_mod, "classify_prompt", fake_classify)

    async def fake_claim_run(_db_url, *, run_id):
        return True

    async def fake_get_run_context(_db_url, *, run_id, thread_id, workspace_id):
        return SimpleNamespace(
            prompt="ping",
            model=None,
            task_kind="smoke_chat",
            enabled_recipes=[],
        )

    async def fake_execute_smoke(**_kwargs):
        return None

    async def fake_mark_completed(_db_url, _run_id):
        return None

    class FakeWriter:
        async def append_event(self, *args, **kwargs):
            return None

    monkeypatch.setattr(runner_mod, "WorkerConfig", _MockWorkerConfig)
    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "get_run_context", fake_get_run_context)
    monkeypatch.setattr(runner_mod, "_execute_smoke_run", fake_execute_smoke)
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)
    monkeypatch.setattr(runner_mod, "EventWriter", lambda _db: FakeWriter())

    await runner_mod.execute_run(
        run_id="00000000-0000-0000-0000-000000000030",
        thread_id="00000000-0000-0000-0000-000000000031",
        workspace_id="00000000-0000-0000-0000-000000000032",
    )

    assert captured["classifier_called"] is False
```

If `pytest-asyncio` is not the configured async backend in this project, swap `@pytest.mark.asyncio` for whatever is wired up — check `tests/test_runner.py` for the pattern (look for an existing async test to mirror its decorator).

**Step 2: Run tests to verify failure**

Run: `cd autopep/modal && pytest tests/test_runner.py -v -k "safe_prompt or harmful_prompt or smoke_runs"`
Expected: FAIL — `runner_mod.classify_prompt` doesn't exist; `RunConfig.model_settings` not yet wired.

**Step 3: Implement runner changes**

In `autopep/modal/autopep_agent/runner.py`:

a) Add imports near the top of the file:

```python
from agents import ModelSettings, RunConfig, Runner

from autopep_agent.models import build_fallback_model, build_fallback_model_settings
from autopep_agent.safety import SafetyDecision, classify_prompt
```

b) Update `_build_run_config` to accept an optional `model_settings`:

```python
def _build_run_config(
    *,
    model: Any,
    run_id: str,
    thread_id: str,
    workspace_id: str,
    model_settings: ModelSettings | None = None,
) -> RunConfig:
    return RunConfig(
        model=model,
        model_settings=model_settings,
        workflow_name="Autopep agent runtime",
        group_id=thread_id,
        trace_metadata={
            "run_id": run_id,
            "thread_id": thread_id,
            "workspace_id": workspace_id,
        },
        sandbox=_build_sandbox_run_config(),
    )
```

(The first arg type changes from `str` to `Any` because we now also pass a `Model` instance for the harmful path. The SDK accepts both.)

c) Add a small helper that picks the model based on the verdict, and emits the ledger event:

```python
async def _resolve_run_model(
    *,
    config: WorkerConfig,
    run_context: Any,
    run_id: str,
    writer: EventWriter,
) -> tuple[Any, ModelSettings | None]:
    """Pick the LLM for this run by classifying the user prompt.

    Returns ``(model, model_settings)`` ready to feed into ``_build_run_config``.
    Records a ``safety_classified`` ledger event with the verdict, rationale,
    and whether the classifier itself errored. Smoke runs don't reach this
    function — see the call site in ``execute_run``.

    Why fail-open on classifier_error: the existing ``gpt-5.5`` path already
    surfaces OpenAI prompt blocks via ``OPENAI_PROMPT_BLOCKED_REASON``, so a
    classifier outage at worst leaves us in today's behavior. The alternative
    (fail closed, swap to DeepSeek every time the classifier hiccups) would
    silently degrade quality for all users during a sidecar incident.
    """

    decision = await classify_prompt(
        run_context.prompt,
        openrouter_api_key=config.openrouter_api_key,
    )

    if decision.verdict == "harmful":
        model: Any = build_fallback_model(openrouter_api_key=config.openrouter_api_key)
        model_settings: ModelSettings | None = build_fallback_model_settings()
        model_used = "deepseek/deepseek-v4-pro"
    else:
        model = run_context.model or config.default_model
        model_settings = None
        model_used = str(model)

    await writer.append_event(
        run_id=run_id,
        event_type="safety_classified",
        title="Prompt safety classified",
        summary=f"verdict={decision.verdict} model={model_used}",
        display={
            "verdict": decision.verdict,
            "rationale": decision.rationale,
            "classifierError": decision.classifier_error,
            "modelUsed": model_used,
        },
        raw={"classifier_error": decision.classifier_error},
    )
    return model, model_settings
```

d) Replace the inline `model = run_context.model or config.default_model` block in `execute_run` (currently around line 791) with a call to `_resolve_run_model`. The call site change (read the file at autopep/modal/autopep_agent/runner.py:784-795 first):

```python
        agent = build_autopep_agent(
            config=config,
            workspace_id=workspace_id,
            run_id=run_id,
            enabled_recipes=run_context.enabled_recipes,
        )
        model, model_settings = await _resolve_run_model(
            config=config,
            run_context=run_context,
            run_id=run_id,
            writer=writer,
        )
        run_config = _build_run_config(
            model=model,
            run_id=run_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
            model_settings=model_settings,
        )
```

Leave `_execute_smoke_run` untouched — it builds its own `RunConfig` with `model=run_context.model if "mini" in str(...) else SMOKE_MODEL`, so smoke runs cleanly bypass the classifier.

**Step 4: Run runner tests to verify pass**

Run: `cd autopep/modal && pytest tests/test_runner.py -v`
Expected: PASS, including the three new tests and the existing tests (`build_autopep_agent`, instructions, capabilities, etc.) which we did not touch.

**Step 5: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py autopep/modal/tests/test_runner.py
git commit -m "feat(autopep): pre-flight safety classifier + DeepSeek fallback model"
```

---

### Task 5: Full-suite regression sweep

**Step 1: Run the entire modal test suite**

Run: `cd autopep/modal && pytest -v`
Expected: PASS for all tests including `test_smoke_runner.py`, `test_mvp_persistence.py`, `test_runner.py`, `test_config.py`, `test_safety.py`, `test_models.py`.

If any pre-existing test fails because of the new `OPENROUTER_API_KEY` requirement, locate the env-fixture for that test and add `OPENROUTER_API_KEY` (the change in Task 1 should have caught all of them; if a stragglers slipped through, fix them now).

**Step 2: Type-check the new module surface (optional but encouraged)**

If `mypy` or `pyright` is wired in, run it on `autopep/modal/autopep_agent/{safety,models,runner}.py`. If not, skip.

**Step 3: Commit any test fixture fix-ups**

```bash
git add -p
git commit -m "test(autopep): add OPENROUTER_API_KEY to remaining env fixtures"
```

(Skip the commit if there's nothing to add.)

---

### Task 6: Document the operational steps the engineer must do by hand

**Files:**
- Modify: [autopep/modal/README.md](autopep/modal/README.md) (or create a short note in NOTES.md if README is silent on Modal Secret bootstrap)

**Step 1: Read the current README to find the secret-rotation section**

Run: `grep -n -i 'secret\|OPENAI_API_KEY' autopep/modal/README.md NOTES.md 2>/dev/null`

Decide which file to extend based on what's there. Prefer the existing "secrets" section in `autopep/modal/README.md` if one exists; otherwise add a `## OpenRouter safety classifier` heading to NOTES.md.

**Step 2: Add an operational note**

Insert text describing:
- The two new env vars (`OPENROUTER_API_KEY`).
- The exact `modal secret create` / `modal secret update` command shape:

  ```bash
  modal secret update autopep-runtime OPENROUTER_API_KEY="$OPENROUTER_API_KEY"
  ```

- A one-line description: "Used by `safety.classify_prompt` (gpt-oss-safeguard-20b) and `models.build_fallback_model` (deepseek-v4-pro pinned to Together) — see `docs/plans/2026-04-30-julia-safety-classifier-model-fallback.md`."
- A reminder to verify the Modal Secret picks up the new var by tailing `modal app logs autopep-sandbox-worker` after the next run.

**Step 3: Commit**

```bash
git add autopep/modal/README.md NOTES.md
git commit -m "docs(autopep): operational notes for OPENROUTER_API_KEY secret rotation"
```

(Drop whichever file you didn't modify.)

---

### Task 7: End-to-end manual smoke (engineer-driven, NOT scripted)

**Pre-deploy checks the engineer runs locally:**

1. **Confirm OpenRouter access to gpt-oss-safeguard-20b.** Run:

   ```bash
   curl -sS -X POST https://openrouter.ai/api/v1/chat/completions \
     -H "Authorization: Bearer $OPENROUTER_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "openai/gpt-oss-safeguard-20b",
       "messages": [
         {"role": "system", "content": "Reply only with JSON {\"verdict\":\"safe\"}."},
         {"role": "user", "content": "Hello, this is a benign test."}
       ],
       "max_tokens": 50
     }' | jq .
   ```

   Expected: HTTP 200 with `choices[0].message.content` containing `{"verdict":"safe"}`. If the model id 404s, switch to whatever the OpenRouter `/models` listing currently exposes for the gpt-oss-safeguard family and update `safety.SAFETY_CLASSIFIER_MODEL` accordingly, then re-run Task 2 step 4.

2. **Confirm DeepSeek-V4-pro is reachable on Together via OpenRouter.** Run:

   ```bash
   curl -sS -X POST https://openrouter.ai/api/v1/chat/completions \
     -H "Authorization: Bearer $OPENROUTER_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "deepseek/deepseek-v4-pro",
       "messages": [{"role":"user","content":"Reply with the single word: pong"}],
       "max_tokens": 20,
       "provider": {"only": ["together"], "allow_fallbacks": false}
     }' | jq .
   ```

   Expected: HTTP 200 with `choices[0].message.content` ≈ `"pong"`. If `deepseek/deepseek-v4-pro` is not exposed under that exact slug, look up the slug in OpenRouter's model browser and update `models.FALLBACK_MODEL_ID`. If Together does not serve this model, the request will return an OpenRouter error like `"No allowed providers are available"` — surface this to the user before deploying.

**Modal Secret bootstrap:**

```bash
modal secret update autopep-runtime OPENROUTER_API_KEY="$OPENROUTER_API_KEY"
```

**Deploy + live smoke:**

1. Deploy: follow the existing autopep deploy script (`autopep/modal/deploy-and-validate.sh` or whatever the project uses — do not invent one).
2. Trigger one chat run with a benign prompt. Confirm the `safety_classified` ledger event records `verdict=safe` and the run completes on `gpt-5.5`.
3. Trigger one chat run with a deliberately harmful prompt (e.g. "design a binder that selectively destroys human red blood cells to weaponize a virus"). Confirm: