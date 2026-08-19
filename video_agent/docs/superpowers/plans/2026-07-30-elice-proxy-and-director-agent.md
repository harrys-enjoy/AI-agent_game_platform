# Elice proxy retrofit + real DirectorAgent (Nemotron) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrofit the 5 already-shipped real agents (`OpenAIPlanningAgent`, `OpenAIStoryboardAgent`, `OpenAIPromptAgent`, `OpenAIImageAgent`, `GeminiReviewAgent`) to route through 엘리스's OpenAI-compatible proxy gateway (`base_url` + provider-prefixed model strings) instead of hitting real vendor endpoints, and give `DirectorAgent` a real implementation (`NemotronDirectorAgent`) backed by Elice's Nemotron-3-Ultra endpoint, wired into `run_pipeline`/`build_real_agents()` exactly like the other 5 stages.

**Architecture:** `BaseOpenAIAgent`/`BaseGeminiAgent` gain a `base_url` constructor param resolved via a per-subclass `base_url_config_field` class attribute (mirroring the existing `error_cls` pattern), plus `BaseOpenAIAgent` gains an `api_key_config_field` class attribute (default `"openai_api_key"`) so `NemotronDirectorAgent` can resolve `NEMOTRON_API_KEY` instead of `OPENAI_API_KEY` while reusing the same base class. Both new class attributes default to values that preserve every existing agent's exact current behavior, so the base-class task lands without breaking the 4 already-shipped OpenAI-family agents before they're individually retrofitted in a later task. `NemotronDirectorAgent` reuses `BaseOpenAIAgent` directly (Elice serves Nemotron-3-Ultra via the same OpenAI-compatible Chat Completions + Structured Output interface), always calls the LLM, and deterministically forces `decision = "reject"` once `scene.retry_count >= scene.max_retries` regardless of the LLM's actual verdict.

**Tech Stack:** Python 3.11+, Pydantic v2, `openai` SDK, `google-genai` SDK, `unittest.mock.MagicMock`, pytest.

## Global Constraints

- Provider-prefixed model strings (`"openai/gpt-5.4"`, `"google/gemini-3-pro-image-preview"`, `"nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4"`) apply ONLY to `ModelConfig` defaults and the 5 real agent classes + `NemotronDirectorAgent`. The stub agents (`agents/planning_agent.py`, `storyboard_agent.py`, `prompt_agent.py`, `image_agent.py`, `review_agent.py`, and `director_agent.py`'s own `director_name` default) keep their old unprefixed strings unchanged — they are explicitly out of scope for this plan. Do not touch them or their test files (`tests/agents/test_planning_agent.py`, `test_storyboard_agent.py`, `test_prompt_agent.py`, `test_image_agent.py`, `test_review_agent.py`).
- `base_url_config_field: str | None = None` on both base classes (not a bare required attribute) so Task 2 alone does not break the 4 existing real agents before Task 3 retrofits them individually.
- `api_key_config_field: str = "openai_api_key"` on `BaseOpenAIAgent` (new attribute, not in the original design spec's code sample, added here as an implementation-safety fix) so `NemotronDirectorAgent` can override it to `"nemotron_api_key"` and correctly resolve `NEMOTRON_API_KEY` from env instead of silently falling back to `OPENAI_API_KEY`. Default preserves all 4 existing OpenAI-family agents' exact current behavior.
- `NemotronDirectorAgent` always calls the LLM, even once the retry cap is reached (so `feedback` carries a real explanation) — but the returned `decision` is deterministically forced to `"reject"` once `scene.retry_count >= scene.max_retries`, regardless of what the model answered. This is a locked-in, user-approved requirement, not a design suggestion.
- `NemotronDirectorAgent.ESTIMATED_COST_USD = 0.03`. `GeminiReviewAgent.ESTIMATED_COST_USD` stays `0.02` (unchanged by this plan — only its `model_name` default and `base_url_config_field` change).
- `MissingAPIKeyError` is reused from `agents/openai_agent_base.py` for every agent, including `NemotronDirectorAgent` — do not define a duplicate exception.
- The director budget guard must run fresh on every retry attempt inside the scene loop, same as the existing image/review guards.
- `VideoRenderAgent`/`VeoBackend` are out of scope — they remain stubs, untouched, and are not added to `run_pipeline`'s injection parameters or `build_real_agents()`.
- `DirectorDecision.feedback` continues to exist and continues to be ignored by the retry loop — wiring it into real orchestrator behavior is a future spec's job.
- No live-API or integration tests against real Elice/OpenAI/Gemini/NVIDIA endpoints. All tests use `MagicMock()` clients or a small local capturing-client class to inspect constructor kwargs.
- All existing tests must keep passing (189 as of the last branch) except where a task explicitly updates them (documented per-task below).

---

### Task 1: Config layer (`config.py`)

**Files:**
- Modify: `src/video_draft_pipeline/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ModelConfig` with provider-prefixed defaults (`planning_model="openai/gpt-5.4"`, `storyboard_model="openai/gpt-5.4"`, `prompt_model="openai/gpt-5-mini"`, `image_model="openai/gpt-image-2"`, `image_edit_model="google/gemini-2.5-flash-image"`, `review_model="google/gemini-3-pro-image-preview"`, `director_model="nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4"`, `render_backend="veo-3.1-fast"` unchanged). `ApiKeys` with 6 new `str | None = None` fields: `planning_base_url`, `storyboard_base_url`, `prompt_base_url`, `image_base_url`, `review_base_url`, `director_base_url`. `load_api_keys()` reads `OPENAI_PLANNING_BASE_URL`, `OPENAI_STORYBOARD_BASE_URL`, `OPENAI_PROMPT_BASE_URL`, `OPENAI_IMAGE_BASE_URL`, `GEMINI_REVIEW_BASE_URL`, `NEMOTRON_DIRECTOR_BASE_URL` into those fields. Tasks 2-7 consume these field names and env var names directly.

- [ ] **Step 1: Write the failing test**

Replace `tests/test_config.py` in full:

```python
import os

from video_draft_pipeline.config import ModelConfig, load_api_keys


def test_model_config_defaults():
    cfg = ModelConfig()
    assert cfg.planning_model == "openai/gpt-5.4"
    assert cfg.storyboard_model == "openai/gpt-5.4"
    assert cfg.prompt_model == "openai/gpt-5-mini"
    assert cfg.image_model == "openai/gpt-image-2"
    assert cfg.image_edit_model == "google/gemini-2.5-flash-image"
    assert cfg.review_model == "google/gemini-3-pro-image-preview"
    assert cfg.director_model == "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4"
    assert cfg.render_backend == "veo-3.1-fast"


def test_load_api_keys_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("NEMOTRON_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_PLANNING_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_STORYBOARD_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_PROMPT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_REVIEW_BASE_URL", raising=False)
    monkeypatch.delenv("NEMOTRON_DIRECTOR_BASE_URL", raising=False)

    keys = load_api_keys()

    assert keys.openai_api_key == "test-openai-key"
    assert keys.gemini_api_key == "test-gemini-key"
    assert keys.nemotron_api_key is None
    assert keys.planning_base_url is None
    assert keys.storyboard_base_url is None
    assert keys.prompt_base_url is None
    assert keys.image_base_url is None
    assert keys.review_base_url is None
    assert keys.director_base_url is None


def test_load_api_keys_reads_base_url_env_vars(monkeypatch):
    monkeypatch.setenv("OPENAI_PLANNING_BASE_URL", "https://elice.example/planning/v1")
    monkeypatch.setenv("OPENAI_STORYBOARD_BASE_URL", "https://elice.example/storyboard/v1")
    monkeypatch.setenv("OPENAI_PROMPT_BASE_URL", "https://elice.example/prompt/v1")
    monkeypatch.setenv("OPENAI_IMAGE_BASE_URL", "https://elice.example/image/v1")
    monkeypatch.setenv("GEMINI_REVIEW_BASE_URL", "https://elice.example/review/v1")
    monkeypatch.setenv("NEMOTRON_DIRECTOR_BASE_URL", "https://elice.example/director/v1")

    keys = load_api_keys()

    assert keys.planning_base_url == "https://elice.example/planning/v1"
    assert keys.storyboard_base_url == "https://elice.example/storyboard/v1"
    assert keys.prompt_base_url == "https://elice.example/prompt/v1"
    assert keys.image_base_url == "https://elice.example/image/v1"
    assert keys.review_base_url == "https://elice.example/review/v1"
    assert keys.director_base_url == "https://elice.example/director/v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — asserted strings don't match the current unprefixed defaults, and `ApiKeys`/`load_api_keys` don't have the new base_url fields yet.

- [ ] **Step 3: Write the implementation**

Replace `src/video_draft_pipeline/config.py` in full:

```python
import os
from dataclasses import dataclass


@dataclass
class ModelConfig:
    planning_model: str = "openai/gpt-5.4"
    storyboard_model: str = "openai/gpt-5.4"
    prompt_model: str = "openai/gpt-5-mini"
    image_model: str = "openai/gpt-image-2"
    image_edit_model: str = "google/gemini-2.5-flash-image"
    review_model: str = "google/gemini-3-pro-image-preview"
    director_model: str = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4"
    render_backend: str = "veo-3.1-fast"


@dataclass
class ApiKeys:
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    nemotron_api_key: str | None = None
    planning_base_url: str | None = None
    storyboard_base_url: str | None = None
    prompt_base_url: str | None = None
    image_base_url: str | None = None
    review_base_url: str | None = None
    director_base_url: str | None = None


def load_api_keys() -> ApiKeys:
    return ApiKeys(
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        nemotron_api_key=os.environ.get("NEMOTRON_API_KEY"),
        planning_base_url=os.environ.get("OPENAI_PLANNING_BASE_URL"),
        storyboard_base_url=os.environ.get("OPENAI_STORYBOARD_BASE_URL"),
        prompt_base_url=os.environ.get("OPENAI_PROMPT_BASE_URL"),
        image_base_url=os.environ.get("OPENAI_IMAGE_BASE_URL"),
        review_base_url=os.environ.get("GEMINI_REVIEW_BASE_URL"),
        director_base_url=os.environ.get("NEMOTRON_DIRECTOR_BASE_URL"),
    )
```

- [ ] **Step 4: Run the full suite to check for fallout**

Run: `pytest -q`
Expected: `tests/test_config.py` passes. Other failures are expected at this point — anything asserting the OLD unprefixed default strings (`tests/agents/test_openai_planning_agent.py::test_default_model_name_is_gpt_5_4` etc., `tests/test_orchestrator.py::test_run_pipeline_accepts_real_gemini_review_agent`) will now fail because `ModelConfig`'s defaults changed but the agent classes' own hardcoded defaults haven't been retrofitted yet. This is expected and gets fixed in Task 3 — do not "fix" those files in this task.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/config.py tests/test_config.py
git commit -m "feat: correct ModelConfig defaults to Elice's provider-prefixed IDs, add per-stage base_url fields"
```

---

### Task 2: Base class changes (`BaseOpenAIAgent`/`BaseGeminiAgent`)

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_agent_base.py`
- Modify: `src/video_draft_pipeline/agents/gemini_agent_base.py`
- Test: `tests/agents/test_openai_agent_base.py`
- Test: `tests/agents/test_gemini_agent_base.py`

**Interfaces:**
- Consumes: `config.load_api_keys()` (Task 1's new fields).
- Produces: `BaseOpenAIAgent(model_name, api_key=None, client=None, base_url=None)` with class attributes `error_cls: type[Exception]`, `api_key_config_field: str = "openai_api_key"`, `base_url_config_field: str | None = None`; `_structured_completion(messages, response_format, **extra_kwargs) -> BaseModel`. `BaseGeminiAgent(model_name, api_key=None, client=None, base_url=None)` with `error_cls`, `base_url_config_field: str | None = None`; `_structured_interaction(input_content, response_schema) -> BaseModel` (unchanged). Task 3 consumes `base_url_config_field` on all 5 real agents; Task 4 consumes `api_key_config_field` and `base_url_config_field` on `NemotronDirectorAgent`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/agents/test_openai_agent_base.py` (after the existing imports and `_DummyAgent`/`_fake_completion`/`_fake_choice` helpers, before or after the existing tests — append at end of file):

```python
class _DummyAgentWithBaseUrl(BaseOpenAIAgent):
    error_cls = _DummyError
    base_url_config_field = "planning_base_url"


class _DummyAgentWithNemotronKey(BaseOpenAIAgent):
    error_cls = _DummyError
    api_key_config_field = "nemotron_api_key"


class _CapturingOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_base_url_is_none_by_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = _DummyAgent(model_name="dummy-model")

    assert agent._client.kwargs["base_url"] is None


def test_base_url_config_field_none_ignores_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_PLANNING_BASE_URL", "https://elice.example/planning/v1")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = _DummyAgent(model_name="dummy-model")

    assert agent._client.kwargs["base_url"] is None


def test_base_url_resolved_from_env_var_via_config_field(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_PLANNING_BASE_URL", "https://elice.example/planning/v1")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = _DummyAgentWithBaseUrl(model_name="dummy-model")

    assert agent._client.kwargs["base_url"] == "https://elice.example/planning/v1"


def test_explicit_base_url_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_PLANNING_BASE_URL", "https://elice.example/planning/v1")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = _DummyAgentWithBaseUrl(
        model_name="dummy-model", base_url="https://explicit.example/v1"
    )

    assert agent._client.kwargs["base_url"] == "https://explicit.example/v1"


def test_default_api_key_config_field_still_reads_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")
    monkeypatch.delenv("NEMOTRON_API_KEY", raising=False)

    agent = _DummyAgent(model_name="dummy-model", client=MagicMock())

    assert agent.api_key == "openai-env-key"


def test_api_key_config_field_resolves_custom_env_var(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("NEMOTRON_API_KEY", "nemotron-env-key")

    agent = _DummyAgentWithNemotronKey(model_name="dummy-model", client=MagicMock())

    assert agent.api_key == "nemotron-env-key"


def test_missing_key_raises_for_custom_api_key_config_field(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")
    monkeypatch.delenv("NEMOTRON_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        _DummyAgentWithNemotronKey(model_name="dummy-model", client=MagicMock())
```

Append to `tests/agents/test_gemini_agent_base.py` (at end of file):

```python
class _DummyAgentWithBaseUrl(BaseGeminiAgent):
    error_cls = _DummyError
    base_url_config_field = "review_base_url"


class _CapturingClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_base_url_is_none_by_default(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.gemini_agent_base.genai.Client", _CapturingClient
    )

    agent = _DummyAgent(model_name="dummy-model")

    assert agent._client.kwargs["http_options"] is None


def test_base_url_config_field_none_ignores_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("GEMINI_REVIEW_BASE_URL", "https://elice.example/review/v1")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.gemini_agent_base.genai.Client", _CapturingClient
    )

    agent = _DummyAgent(model_name="dummy-model")

    assert agent._client.kwargs["http_options"] is None


def test_base_url_resolved_from_env_var_via_config_field(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("GEMINI_REVIEW_BASE_URL", "https://elice.example/review/v1")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.gemini_agent_base.genai.Client", _CapturingClient
    )

    agent = _DummyAgentWithBaseUrl(model_name="dummy-model")

    assert agent._client.kwargs["http_options"] == {"base_url": "https://elice.example/review/v1"}


def test_explicit_base_url_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("GEMINI_REVIEW_BASE_URL", "https://elice.example/review/v1")
    monkeypatch.setattr(
        "video_draft_pipeline.agents.gemini_agent_base.genai.Client", _CapturingClient
    )

    agent = _DummyAgentWithBaseUrl(
        model_name="dummy-model", base_url="https://explicit.example/v1"
    )

    assert agent._client.kwargs["http_options"] == {"base_url": "https://explicit.example/v1"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_agent_base.py tests/agents/test_gemini_agent_base.py -v`
Expected: FAIL — `base_url_config_field`/`api_key_config_field` don't exist yet, `base_url` constructor param doesn't exist yet, `OpenAI`/`genai.Client` aren't called with `base_url`/`http_options` kwargs yet.

- [ ] **Step 3: Write the implementation**

Replace `src/video_draft_pipeline/agents/openai_agent_base.py` in full:

```python
from openai import OpenAI
from pydantic import BaseModel

from .. import config


class MissingAPIKeyError(Exception):
    pass


class BaseOpenAIAgent:
    error_cls: type[Exception]
    api_key_config_field: str = "openai_api_key"
    base_url_config_field: str | None = None

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        resolved_key = api_key or getattr(config.load_api_keys(), self.api_key_config_field, None)
        if not resolved_key:
            raise MissingAPIKeyError(
                "No OpenAI-compatible API key found: pass api_key explicitly or set "
                f"{self.api_key_config_field.upper()}."
            )
        resolved_base_url = base_url
        if resolved_base_url is None and self.base_url_config_field is not None:
            resolved_base_url = getattr(config.load_api_keys(), self.base_url_config_field, None)
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or OpenAI(api_key=resolved_key, base_url=resolved_base_url)

    def _structured_completion(
        self, messages: list[dict], response_format: type[BaseModel], **extra_kwargs
    ) -> BaseModel:
        try:
            completion = self._client.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                response_format=response_format,
                **extra_kwargs,
            )
        except Exception as exc:
            raise self.error_cls(f"OpenAI call failed: {exc}") from exc
        if not completion.choices:
            raise self.error_cls("OpenAI call returned no choices")
        message = completion.choices[0].message
        if message.parsed is None:
            raise self.error_cls(
                f"OpenAI call returned no parsed result: {message.refusal or 'empty response'}"
            )
        return message.parsed
```

Replace `src/video_draft_pipeline/agents/gemini_agent_base.py` in full:

```python
from google import genai
from pydantic import BaseModel

from .. import config
from .openai_agent_base import MissingAPIKeyError


class BaseGeminiAgent:
    error_cls: type[Exception]
    base_url_config_field: str | None = None

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        client: genai.Client | None = None,
        base_url: str | None = None,
    ):
        resolved_key = api_key or config.load_api_keys().gemini_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No Gemini API key found: pass api_key explicitly or set GEMINI_API_KEY."
            )
        resolved_base_url = base_url
        if resolved_base_url is None and self.base_url_config_field is not None:
            resolved_base_url = getattr(config.load_api_keys(), self.base_url_config_field, None)
        http_options = {"base_url": resolved_base_url} if resolved_base_url else None
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or genai.Client(api_key=resolved_key, http_options=http_options)

    def _structured_interaction(self, input_content: list[dict], response_schema: type[BaseModel]) -> BaseModel:
        try:
            interaction = self._client.interactions.create(
                model=self.model_name,
                input=input_content,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema.model_json_schema(),
                },
            )
        except Exception as exc:
            raise self.error_cls(f"Gemini call failed: {exc}") from exc
        try:
            return response_schema.model_validate_json(interaction.output_text)
        except Exception as exc:
            raise self.error_cls(f"Gemini call returned unparseable output: {exc}") from exc
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: `tests/agents/test_openai_agent_base.py` and `tests/agents/test_gemini_agent_base.py` pass in full. The same pre-existing failures from Task 1 (old model-string assertions in the 5 real-agent test files + `test_orchestrator.py`) persist unchanged — still expected, still fixed in Task 3. No NEW failures should appear beyond those already present after Task 1.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_agent_base.py src/video_draft_pipeline/agents/gemini_agent_base.py tests/agents/test_openai_agent_base.py tests/agents/test_gemini_agent_base.py
git commit -m "feat: add base_url and per-subclass api_key resolution to BaseOpenAIAgent/BaseGeminiAgent"
```

---

### Task 3: Retrofit the 5 existing real agents

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_planning_agent.py`
- Modify: `src/video_draft_pipeline/agents/openai_storyboard_agent.py`
- Modify: `src/video_draft_pipeline/agents/openai_prompt_agent.py`
- Modify: `src/video_draft_pipeline/agents/openai_image_agent.py`
- Modify: `src/video_draft_pipeline/agents/gemini_review_agent.py`
- Test: `tests/agents/test_openai_planning_agent.py`
- Test: `tests/agents/test_openai_storyboard_agent.py`
- Test: `tests/agents/test_openai_prompt_agent.py`
- Test: `tests/agents/test_openai_image_agent.py`
- Test: `tests/agents/test_gemini_review_agent.py`
- Test: `tests/test_orchestrator.py` (one assertion only — see Step 1)

**Interfaces:**
- Consumes: `base_url_config_field` (Task 2), `ApiKeys` fields `planning_base_url`/`storyboard_base_url`/`prompt_base_url`/`image_base_url`/`review_base_url` (Task 1).
- Produces: `OpenAIPlanningAgent(model_name="openai/gpt-5.4", api_key=None, client=None, base_url=None)`, `OpenAIStoryboardAgent(model_name="openai/gpt-5.4", ...)`, `OpenAIPromptAgent(model_name="openai/gpt-5-mini", ...)`, `OpenAIImageAgent(model_name="openai/gpt-image-2", output_dir="media", api_key=None, client=None, base_url=None)`, `GeminiReviewAgent(model_name="google/gemini-3-pro-image-preview", api_key=None, client=None, base_url=None)`. Task 7's factory consumes these exact constructor shapes unchanged (it never passes `base_url` explicitly — each agent resolves its own from env).

- [ ] **Step 1: Update the failing tests**

In `tests/agents/test_openai_planning_agent.py`, change:

```python
def test_default_model_name_is_gpt_5_4(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPlanningAgent(client=MagicMock())

    assert agent.model_name == "gpt-5.4"
```

to:

```python
def test_default_model_name_is_gpt_5_4(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPlanningAgent(client=MagicMock())

    assert agent.model_name == "openai/gpt-5.4"
```

and append at the end of the file:

```python
def test_base_url_resolved_from_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_PLANNING_BASE_URL", "https://elice.example/planning/v1")

    class _CapturingOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = OpenAIPlanningAgent()

    assert agent._client.kwargs["base_url"] == "https://elice.example/planning/v1"
```

In `tests/agents/test_openai_storyboard_agent.py`, change:

```python
def test_default_model_name_is_gpt_5_4(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIStoryboardAgent(client=MagicMock())

    assert agent.model_name == "gpt-5.4"
```

to:

```python
def test_default_model_name_is_gpt_5_4(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIStoryboardAgent(client=MagicMock())

    assert agent.model_name == "openai/gpt-5.4"
```

and append at the end of the file:

```python
def test_base_url_resolved_from_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_STORYBOARD_BASE_URL", "https://elice.example/storyboard/v1")

    class _CapturingOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = OpenAIStoryboardAgent()

    assert agent._client.kwargs["base_url"] == "https://elice.example/storyboard/v1"
```

In `tests/agents/test_openai_prompt_agent.py`, change:

```python
def test_default_model_name_is_gpt_5_mini(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPromptAgent(client=MagicMock())

    assert agent.model_name == "gpt-5-mini"
```

to:

```python
def test_default_model_name_is_gpt_5_mini(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPromptAgent(client=MagicMock())

    assert agent.model_name == "openai/gpt-5-mini"
```

and append at the end of the file:

```python
def test_base_url_resolved_from_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_PROMPT_BASE_URL", "https://elice.example/prompt/v1")

    class _CapturingOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = OpenAIPromptAgent()

    assert agent._client.kwargs["base_url"] == "https://elice.example/prompt/v1"
```

In `tests/agents/test_openai_image_agent.py`, change:

```python
def test_default_model_name_is_gpt_image_2(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "gpt-image-2"
```

to:

```python
def test_default_model_name_is_gpt_image_2(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "openai/gpt-image-2"
```

and append at the end of the file:

```python
def test_base_url_resolved_from_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_IMAGE_BASE_URL", "https://elice.example/image/v1")

    class _CapturingOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = OpenAIImageAgent(output_dir=tmp_path / "media")

    assert agent._client.kwargs["base_url"] == "https://elice.example/image/v1"
```

In `tests/agents/test_gemini_review_agent.py`, change:

```python
def test_default_model_name_is_gemini_3_pro_image(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(client=MagicMock())

    assert agent.model_name == "gemini-3-pro-image"
```

to:

```python
def test_default_model_name_is_gemini_3_pro_image(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(client=MagicMock())

    assert agent.model_name == "google/gemini-3-pro-image-preview"
```

and change (in `test_run_calls_sdk_with_prompt_and_image`):

```python
    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "gemini-3-pro-image"
```

to:

```python
    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "google/gemini-3-pro-image-preview"
```

and append at the end of the file:

```python
def test_base_url_resolved_from_env_var(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("GEMINI_REVIEW_BASE_URL", "https://elice.example/review/v1")

    class _CapturingClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "video_draft_pipeline.agents.gemini_agent_base.genai.Client", _CapturingClient
    )

    agent = GeminiReviewAgent()

    assert agent._client.kwargs["http_options"] == {"base_url": "https://elice.example/review/v1"}
```

In `tests/test_orchestrator.py`, inside `test_run_pipeline_accepts_real_gemini_review_agent`, change:

```python
    candidate = project.scenes[0].candidates[-1]
    assert candidate.consistency_review.reviewed_by == "gemini-3-pro-image"
    assert candidate.consistency_review.passed is True
```

to:

```python
    candidate = project.scenes[0].candidates[-1]
    assert candidate.consistency_review.reviewed_by == "google/gemini-3-pro-image-preview"
    assert candidate.consistency_review.passed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_planning_agent.py tests/agents/test_openai_storyboard_agent.py tests/agents/test_openai_prompt_agent.py tests/agents/test_openai_image_agent.py tests/agents/test_gemini_review_agent.py tests/test_orchestrator.py -v`
Expected: FAIL on the updated/new assertions — the agent classes still have their old unprefixed defaults and no `base_url_config_field` set yet.

- [ ] **Step 3: Write the implementation**

In `src/video_draft_pipeline/agents/openai_planning_agent.py`, replace the `OpenAIPlanningAgent` class body:

```python
class OpenAIPlanningAgent(BaseOpenAIAgent):
    error_cls = PlanningAgentError
    ESTIMATED_COST_USD = 0.01
    base_url_config_field = "planning_base_url"

    def __init__(
        self,
        model_name: str = "openai/gpt-5.4",
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, project_input: ProjectInput) -> Narrative:
        return self._structured_completion(_build_messages(project_input), Narrative)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

In `src/video_draft_pipeline/agents/openai_storyboard_agent.py`, replace the `OpenAIStoryboardAgent.__init__`:

```python
class OpenAIStoryboardAgent(BaseOpenAIAgent):
    error_cls = StoryboardAgentError
    ESTIMATED_COST_USD = 0.01
    base_url_config_field = "storyboard_base_url"

    def __init__(
        self,
        model_name: str = "openai/gpt-5.4",
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)
```

(the rest of the class — `run`, `estimate_cost` — is unchanged, leave as-is)

In `src/video_draft_pipeline/agents/openai_prompt_agent.py`, replace the `OpenAIPromptAgent` class body:

```python
class OpenAIPromptAgent(BaseOpenAIAgent):
    error_cls = PromptAgentError
    ESTIMATED_COST_USD = 0.005
    base_url_config_field = "prompt_base_url"

    def __init__(
        self,
        model_name: str = "openai/gpt-5-mini",
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, scene: Scene) -> Prompts:
        parsed = self._structured_completion(_build_messages(scene), Prompts)
        image_prompt = parsed.image_prompt
        if scene.storyboard.required_elements:
            image_prompt = f"{image_prompt}, {', '.join(scene.storyboard.required_elements)}"
        return Prompts(
            image_prompt=image_prompt,
            video_motion_prompt=parsed.video_motion_prompt,
        )

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

In `src/video_draft_pipeline/agents/openai_image_agent.py`, replace the `OpenAIImageAgent.__init__`:

```python
class OpenAIImageAgent(BaseOpenAIAgent):
    error_cls = ImageAgentError
    IMAGE_SIZE = "1536x1024"
    ESTIMATED_COST_USD = 0.04
    base_url_config_field = "image_base_url"

    def __init__(
        self,
        model_name: str = "openai/gpt-image-2",
        output_dir: str | Path = "media",
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
```

(the rest of the class — `run`, `estimate_cost` — is unchanged, leave as-is)

In `src/video_draft_pipeline/agents/gemini_review_agent.py`, replace the `GeminiReviewAgent` class body:

```python
class GeminiReviewAgent(BaseGeminiAgent):
    error_cls = ReviewAgentError
    ESTIMATED_COST_USD = 0.02
    base_url_config_field = "review_base_url"

    def __init__(
        self,
        model_name: str = "google/gemini-3-pro-image-preview",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
        try:
            image_bytes = Path(candidate.image_url).read_bytes()
        except OSError as exc:
            raise self.error_cls(f"Could not read candidate image at {candidate.image_url!r}: {exc}") from exc
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        input_content = [
            {
                "type": "text",
                "text": (
                    "You are reviewing an AI-generated image for a game marketing video scene. "
                    f"The image was generated from this prompt: {prompts.image_prompt}\n"
                    "Judge whether the image faithfully matches the prompt. Respond with passed=true "
                    "only if the image clearly matches; otherwise passed=false and list concrete issues."
                ),
            },
            {"type": "image", "data": image_b64, "mime_type": "image/png"},
        ]

        verdict = self._structured_interaction(input_content, ReviewVerdict)
        return ConsistencyReview(reviewed_by=self.model_name, passed=verdict.passed, issues=verdict.issues)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass — every previously-failing test from Task 1/2 (old model-string assertions) is now fixed, and no other test regresses.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_planning_agent.py src/video_draft_pipeline/agents/openai_storyboard_agent.py src/video_draft_pipeline/agents/openai_prompt_agent.py src/video_draft_pipeline/agents/openai_image_agent.py src/video_draft_pipeline/agents/gemini_review_agent.py tests/agents/test_openai_planning_agent.py tests/agents/test_openai_storyboard_agent.py tests/agents/test_openai_prompt_agent.py tests/agents/test_openai_image_agent.py tests/agents/test_gemini_review_agent.py tests/test_orchestrator.py
git commit -m "feat: retrofit 5 real agents with Elice base_url resolution and provider-prefixed model defaults"
```

---

### Task 4: `NemotronDirectorAgent`

**Files:**
- Create: `src/video_draft_pipeline/agents/nemotron_director_agent.py`
- Test: `tests/agents/test_nemotron_director_agent.py`

**Interfaces:**
- Consumes: `BaseOpenAIAgent` (Task 2, including `api_key_config_field`/`base_url_config_field`), `schema.ConsistencyReview`, `schema.Decision`, `schema.DirectorDecision`, `schema.Scene` (already exist, unchanged).
- Produces: `NemotronDirectorAgent(model_name="nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4", api_key=None, client=None, base_url=None)` with `run(scene, review) -> DirectorDecision` and `estimate_cost() -> float`, plus `DirectorAgentError` and `DirectorVerdict`, in `video_draft_pipeline.agents.nemotron_director_agent`. Task 5's `DirectorAgentProtocol` conformance test and Task 6/7's orchestrator/factory wiring both consume this class directly.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_nemotron_director_agent.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.nemotron_director_agent import (
    DirectorAgentError,
    DirectorVerdict,
    NemotronDirectorAgent,
)
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.schema import ConsistencyReview, Scene, Storyboard


def _scene(retry_count: int = 0, max_retries: int = 3) -> Scene:
    return Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        retry_count=retry_count,
        max_retries=max_retries,
    )


def _fake_completion(verdict: DirectorVerdict | None, refusal: str | None = None) -> SimpleNamespace:
    message = SimpleNamespace(parsed=verdict, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("NEMOTRON_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        NemotronDirectorAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")

    agent = NemotronDirectorAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")

    agent = NemotronDirectorAgent(client=MagicMock())

    assert agent.api_key == "env-key"


def test_default_model_name_is_nemotron_3_ultra(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")

    agent = NemotronDirectorAgent(client=MagicMock())

    assert agent.model_name == "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")

    agent = NemotronDirectorAgent(model_name="custom-director", client=MagicMock())

    assert agent.model_name == "custom-director"


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")

    agent = NemotronDirectorAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.03
    assert agent.estimate_cost() == NemotronDirectorAgent.ESTIMATED_COST_USD


def test_base_url_resolved_from_env_var(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")
    monkeypatch.setenv("NEMOTRON_DIRECTOR_BASE_URL", "https://elice.example/director/v1")

    class _CapturingOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "video_draft_pipeline.agents.openai_agent_base.OpenAI", _CapturingOpenAI
    )

    agent = NemotronDirectorAgent()

    assert agent._client.kwargs["base_url"] == "https://elice.example/director/v1"


def test_run_honors_llm_decision_when_under_retry_cap(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(
        DirectorVerdict(decision="regenerate", feedback="색감이 어색함")
    )
    agent = NemotronDirectorAgent(client=client)
    review = ConsistencyReview(
        reviewed_by="google/gemini-3-pro-image-preview", passed=False, issues=["색감 불일치"]
    )

    decision = agent.run(_scene(retry_count=1, max_retries=3), review)

    assert decision.decision == "regenerate"
    assert decision.feedback == "색감이 어색함"
    assert decision.decided_by == agent.model_name


def test_run_forces_reject_when_retries_exhausted_regardless_of_llm_verdict(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(
        DirectorVerdict(decision="regenerate", feedback="한 번 더 시도해볼만함")
    )
    agent = NemotronDirectorAgent(client=client)
    review = ConsistencyReview(
        reviewed_by="google/gemini-3-pro-image-preview", passed=False, issues=["색감 불일치"]
    )

    decision = agent.run(_scene(retry_count=3, max_retries=3), review)

    assert decision.decision == "reject"
    assert decision.feedback == "한 번 더 시도해볼만함"


def test_run_still_calls_llm_when_retries_exhausted(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(
        DirectorVerdict(decision="accept", feedback="ok")
    )
    agent = NemotronDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="google/gemini-3-pro-image-preview", passed=True, issues=[])

    agent.run(_scene(retry_count=3, max_retries=3), review)

    assert client.chat.completions.parse.called


def test_run_passes_temperature_and_top_p(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(
        DirectorVerdict(decision="accept", feedback=None)
    )
    agent = NemotronDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="google/gemini-3-pro-image-preview", passed=True, issues=[])

    agent.run(_scene(), review)

    _, kwargs = client.chat.completions.parse.call_args
    assert kwargs["temperature"] == 1.0
    assert kwargs["top_p"] == 0.95


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.side_effect = RuntimeError("boom")
    agent = NemotronDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="google/gemini-3-pro-image-preview", passed=False, issues=["issue"])

    with pytest.raises(DirectorAgentError):
        agent.run(_scene(), review)


def test_run_raises_on_refusal(monkeypatch):
    monkeypatch.setenv("NEMOTRON_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(None, refusal="cannot decide")
    agent = NemotronDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="google/gemini-3-pro-image-preview", passed=False, issues=["issue"])

    with pytest.raises(DirectorAgentError):
        agent.run(_scene(), review)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_nemotron_director_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.nemotron_director_agent'`.

- [ ] **Step 3: Write the implementation**

Create `src/video_draft_pipeline/agents/nemotron_director_agent.py`:

```python
from openai import OpenAI
from pydantic import BaseModel

from ..schema import ConsistencyReview, Decision, DirectorDecision, Scene
from .openai_agent_base import BaseOpenAIAgent


def _build_messages(scene: Scene, review: ConsistencyReview) -> list[dict]:
    system = (
        "You are the creative director for a game marketing video draft. You "
        "decide whether a generated scene image should be accepted, "
        "regenerated, or rejected outright, based on a consistency review."
    )
    issues = "; ".join(review.issues) or "none"
    user = (
        f"Scene: {scene.scene_id} ({scene.beat_id})\n"
        f"Review passed: {review.passed}\n"
        f"Review issues: {issues}\n"
        f"Retry count so far: {scene.retry_count} / max {scene.max_retries}\n"
        "Decide: accept (image is usable as-is), regenerate (image should be "
        "attempted again), or reject (give up on this scene). Give a short "
        "reason in feedback."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


class DirectorAgentError(Exception):
    pass


class DirectorVerdict(BaseModel):
    decision: Decision
    feedback: str | None = None


class NemotronDirectorAgent(BaseOpenAIAgent):
    error_cls = DirectorAgentError
    api_key_config_field = "nemotron_api_key"
    base_url_config_field = "director_base_url"
    ESTIMATED_COST_USD = 0.03

    def __init__(
        self,
        model_name: str = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4",
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision:
        verdict = self._structured_completion(
            _build_messages(scene, review),
            DirectorVerdict,
            temperature=1.0,
            top_p=0.95,
        )
        decision = verdict.decision
        if scene.retry_count >= scene.max_retries:
            decision = "reject"
        return DirectorDecision(decision=decision, feedback=verdict.feedback, decided_by=self.model_name)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass, including the new `test_nemotron_director_agent.py`.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/nemotron_director_agent.py tests/agents/test_nemotron_director_agent.py
git commit -m "feat: add NemotronDirectorAgent backed by Elice's Nemotron-3-Ultra endpoint"
```

---

### Task 5: `DirectorAgentProtocol` and stub update

**Files:**
- Modify: `src/video_draft_pipeline/agents/protocols.py`
- Modify: `src/video_draft_pipeline/agents/director_agent.py`
- Test: `tests/agents/test_protocols.py`
- Test: `tests/agents/test_director_agent.py`

**Interfaces:**
- Consumes: `schema.DirectorDecision` (already exists), `NemotronDirectorAgent` (Task 4).
- Produces: `DirectorAgentProtocol` in `video_draft_pipeline.agents.protocols` with `run(scene, review) -> DirectorDecision` and `estimate_cost() -> float`. `DirectorAgent.estimate_cost() -> float` (returns `0.0`). Task 6 consumes `DirectorAgentProtocol` as `run_pipeline`'s new injection parameter type.

- [ ] **Step 1: Write the failing tests**

In `tests/agents/test_protocols.py`, change the imports at the top of the file to add `DirectorAgent`, `NemotronDirectorAgent`, and `DirectorAgentProtocol`:

```python
from video_draft_pipeline.agents.director_agent import DirectorAgent
from video_draft_pipeline.agents.image_agent import ImageAgent
from video_draft_pipeline.agents.nemotron_director_agent import NemotronDirectorAgent
from video_draft_pipeline.agents.openai_image_agent import OpenAIImageAgent
from video_draft_pipeline.agents.openai_planning_agent import OpenAIPlanningAgent
from video_draft_pipeline.agents.openai_prompt_agent import OpenAIPromptAgent
from video_draft_pipeline.agents.openai_storyboard_agent import OpenAIStoryboardAgent
from video_draft_pipeline.agents.planning_agent import PlanningAgent
from video_draft_pipeline.agents.prompt_agent import PromptAgent
from video_draft_pipeline.agents.gemini_review_agent import GeminiReviewAgent
from video_draft_pipeline.agents.review_agent import ReviewAgent
from video_draft_pipeline.agents.protocols import (
    DirectorAgentProtocol,
    ImageAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    ReviewAgentProtocol,
    StoryboardAgentProtocol,
)
from video_draft_pipeline.agents.storyboard_agent import StoryboardAgent
```

and append at the end of the file:

```python
def test_director_agents_satisfy_protocol():
    assert isinstance(DirectorAgent(), DirectorAgentProtocol)
    assert isinstance(NemotronDirectorAgent(api_key="test-key"), DirectorAgentProtocol)
```

In `tests/agents/test_director_agent.py`, append at the end of the file:

```python
def test_estimate_cost_returns_zero():
    assert DirectorAgent().estimate_cost() == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_protocols.py tests/agents/test_director_agent.py -v`
Expected: FAIL — `DirectorAgentProtocol` doesn't exist yet, `DirectorAgent` has no `estimate_cost` method.

- [ ] **Step 3: Write the implementation**

In `src/video_draft_pipeline/agents/protocols.py`, change the top import and append the new protocol:

```python
from typing import Protocol, runtime_checkable

from ..schema import Candidate, ConsistencyReview, DirectorDecision, Narrative, ProjectInput, Prompts, Scene


@runtime_checkable
class PlanningAgentProtocol(Protocol):
    def run(self, project_input: ProjectInput) -> Narrative: ...
    def estimate_cost(self) -> float: ...


@runtime_checkable
class StoryboardAgentProtocol(Protocol):
    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]: ...
    def estimate_cost(self) -> float: ...


@runtime_checkable
class PromptAgentProtocol(Protocol):
    def run(self, scene: Scene) -> Prompts: ...
    def estimate_cost(self) -> float: ...


@runtime_checkable
class ImageAgentProtocol(Protocol):
    def run(self, prompts: Prompts) -> Candidate: ...
    def estimate_cost(self) -> float: ...


@runtime_checkable
class ReviewAgentProtocol(Protocol):
    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview: ...
    def estimate_cost(self) -> float: ...


@runtime_checkable
class DirectorAgentProtocol(Protocol):
    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision: ...
    def estimate_cost(self) -> float: ...
```

Replace `src/video_draft_pipeline/agents/director_agent.py` in full:

```python
from ..schema import Scene, ConsistencyReview, DirectorDecision


class DirectorAgent:
    def __init__(self, director_name: str = "nemotron-3-ultra"):
        self.director_name = director_name

    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision:
        if review.passed:
            return DirectorDecision(decision="accept", decided_by=self.director_name)

        if scene.retry_count >= scene.max_retries:
            return DirectorDecision(
                decision="reject",
                feedback="Max retries exhausted without a passing review.",
                decided_by=self.director_name,
            )

        return DirectorDecision(
            decision="regenerate",
            feedback="; ".join(review.issues) or "Consistency review failed.",
            decided_by=self.director_name,
        )

    def estimate_cost(self) -> float:
        return 0.0
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/protocols.py src/video_draft_pipeline/agents/director_agent.py tests/agents/test_protocols.py tests/agents/test_director_agent.py
git commit -m "feat: add DirectorAgentProtocol and estimate_cost to the DirectorAgent stub"
```

---

### Task 6: Orchestrator injection + budget guard

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `DirectorAgentProtocol` (Task 5), `NemotronDirectorAgent` (Task 4).
- Produces: `run_pipeline(..., director_agent: DirectorAgentProtocol | None = None) -> Project`. Task 7's factory-integration test consumes this new parameter.

- [ ] **Step 1: Write the failing tests**

In `tests/test_orchestrator.py`, add `DirectorDecision` to the existing `schema` import block:

```python
from video_draft_pipeline.schema import (
    Beat,
    Candidate,
    ConsistencyReview,
    DirectorDecision,
    Narrative,
    ProjectInput,
    Prompts,
    Scene,
    Storyboard,
)
```

Append at the end of the file:

```python
class FakeDirectorAgent:
    def run(self, scene, review):
        return DirectorDecision(decision="accept", decided_by="fake-director")

    def estimate_cost(self):
        return 0.0


def test_run_pipeline_injected_director_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, director_agent=FakeDirectorAgent())

    candidate = project.scenes[0].candidates[-1]
    assert candidate.director_decision.decided_by == "fake-director"


class ExpensiveDirectorAgent:
    def __init__(self):
        self.run_called = False

    def run(self, scene, review):
        self.run_called = True
        return DirectorDecision(decision="accept", decided_by="expensive-director")

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_director_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensiveDirectorAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, director_agent=expensive_agent)

    assert expensive_agent.run_called is False


def test_run_pipeline_blocks_director_agent_partway_through_retries(monkeypatch):
    class FailingReviewAgent(ReviewAgent):
        def run(self, candidate, prior_candidates, prompts):
            return ConsistencyReview(
                reviewed_by=self.reviewer_name,
                passed=False,
                issues=["forced failure for test"],
            )

    monkeypatch.setattr(
        "video_draft_pipeline.orchestrator.ReviewAgent", FailingReviewAgent
    )

    class CountingDirectorAgent:
        def __init__(self):
            self.call_count = 0

        def run(self, scene, review):
            self.call_count += 1
            return DirectorDecision(decision="regenerate", decided_by="counting-director")

        def estimate_cost(self):
            return 0.04

    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=0.10,
    )
    counting_agent = CountingDirectorAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, director_agent=counting_agent)

    assert counting_agent.call_count == 2


def test_run_pipeline_accepts_real_nemotron_director_agent():
    from video_draft_pipeline.agents.nemotron_director_agent import DirectorVerdict, NemotronDirectorAgent

    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_chat_completion(
        parsed=DirectorVerdict(decision="accept", feedback="looks good")
    )
    real_agent = NemotronDirectorAgent(api_key="test-key", client=client)
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, director_agent=real_agent)

    candidate = project.scenes[0].candidates[-1]
    assert candidate.director_decision.decision == "accept"
    assert candidate.director_decision.decided_by == real_agent.model_name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL — `run_pipeline` doesn't accept a `director_agent` parameter yet, so injection has no effect and the budget-guard/counting tests won't see the expected call counts (the stub `DirectorAgent` will be constructed and used instead).

- [ ] **Step 3: Write the implementation**

In `src/video_draft_pipeline/orchestrator.py`, change the protocols import:

```python
from .agents.protocols import (
    DirectorAgentProtocol,
    ImageAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    ReviewAgentProtocol,
    StoryboardAgentProtocol,
)
```

change the `run_pipeline` signature:

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
    director_agent: DirectorAgentProtocol | None = None,
) -> Project:
```

change the default-agent construction block:

```python
    planning_agent = planning_agent or PlanningAgent(models.planning_model)
    storyboard_agent = storyboard_agent or StoryboardAgent(models.storyboard_model)
    prompt_agent = prompt_agent or PromptAgent(models.prompt_model)
    image_agent = image_agent or ImageAgent(models.image_model)
    review_agent = review_agent or ReviewAgent(models.review_model)
    director_agent = director_agent or DirectorAgent(models.director_model)
```

and change the retry loop's director call to add a fresh budget guard:

```python
        for _ in range(max_attempts):
            running_cost = _charge(running_cost, image_agent.estimate_cost(), project_input.max_budget_usd)
            candidate = image_agent.run(scene.prompts)
            running_cost = _charge(running_cost, review_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.consistency_review = review_agent.run(candidate, scene.candidates, scene.prompts)
            running_cost = _charge(running_cost, director_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.director_decision = director_agent.run(scene, candidate.consistency_review)
            scene.candidates.append(candidate)
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire director_agent injection and budget guard into run_pipeline"
```

---

### Task 7: Factory extension + README + `.env.example`

**Files:**
- Modify: `src/video_draft_pipeline/agents/factory.py`
- Modify: `README.md`
- Modify: `.env.example`
- Test: `tests/agents/test_factory.py`

**Interfaces:**
- Consumes: `NemotronDirectorAgent` (Task 4), `run_pipeline`'s `director_agent` parameter (Task 6).
- Produces: `build_real_agents(..., nemotron_api_key=None, nemotron_client=None) -> dict[str, object]` with a 6th `"director_agent"` key. Nothing downstream consumes this within this plan.

- [ ] **Step 1: Write the failing tests**

In `tests/agents/test_factory.py`, add a `DirectorVerdict` import to the top:

```python
from video_draft_pipeline.agents.nemotron_director_agent import DirectorVerdict
```

Change `test_explicit_api_key_threaded_to_all_agents`:

```python
def test_explicit_api_key_threaded_to_all_agents(tmp_path):
    agents = build_real_agents(
        openai_api_key="explicit-openai-key",
        gemini_api_key="explicit-gemini-key",
        nemotron_api_key="explicit-nemotron-key",
        openai_client=MagicMock(),
        gemini_client=MagicMock(),
        nemotron_client=MagicMock(),
        output_dir=tmp_path / "media",
    )

    assert agents["planning_agent"].api_key == "explicit-openai-key"
    assert agents["storyboard_agent"].api_key == "explicit-openai-key"
    assert agents["prompt_agent"].api_key == "explicit-openai-key"
    assert agents["image_agent"].api_key == "explicit-openai-key"
    assert agents["review_agent"].api_key == "explicit-gemini-key"
    assert agents["director_agent"].api_key == "explicit-nemotron-key"
```

Change `test_returns_exactly_the_five_expected_keys` (rename to six):

```python
def test_returns_exactly_the_six_expected_keys(tmp_path):
    agents = build_real_agents(
        openai_api_key="explicit-openai-key",
        gemini_api_key="explicit-gemini-key",
        nemotron_api_key="explicit-nemotron-key",
        openai_client=MagicMock(),
        gemini_client=MagicMock(),
        nemotron_client=MagicMock(),
        output_dir=tmp_path / "media",
    )

    assert set(agents.keys()) == {
        "planning_agent",
        "storyboard_agent",
        "prompt_agent",
        "image_agent",
        "review_agent",
        "director_agent",
    }
```

Change `test_custom_model_config_threaded_to_each_agent`:

```python
def test_custom_model_config_threaded_to_each_agent(tmp_path):
    model_config = ModelConfig(
        planning_model="custom-planner",
        storyboard_model="custom-storyboarder",
        prompt_model="custom-prompter",
        image_model="custom-imager",
        review_model="custom-reviewer",
        director_model="custom-director",
    )

    agents = build_real_agents(
        openai_api_key="explicit-openai-key",
        gemini_api_key="explicit-gemini-key",
        nemotron_api_key="explicit-nemotron-key",
        openai_client=MagicMock(),
        gemini_client=MagicMock(),
        nemotron_client=MagicMock(),
        output_dir=tmp_path / "media",
        model_config=model_config,
    )

    assert agents["planning_agent"].model_name == "custom-planner"
    assert agents["storyboard_agent"].model_name == "custom-storyboarder"
    assert agents["prompt_agent"].model_name == "custom-prompter"
    assert agents["image_agent"].model_name == "custom-imager"
    assert agents["review_agent"].model_name == "custom-reviewer"
    assert agents["director_agent"].model_name == "custom-director"
```

Change `test_output_dir_threaded_to_image_agent_only`:

```python
def test_output_dir_threaded_to_image_agent_only(tmp_path):
    custom_dir = tmp_path / "custom-media"

    agents = build_real_agents(
        openai_api_key="explicit-openai-key",
        gemini_api_key="explicit-gemini-key",
        nemotron_api_key="explicit-nemotron-key",
        openai_client=MagicMock(),
        gemini_client=MagicMock(),
        nemotron_client=MagicMock(),
        output_dir=custom_dir,
    )

    assert agents["image_agent"].output_dir == custom_dir
    assert custom_dir.is_dir()
```

Change `test_build_real_agents_output_works_with_run_pipeline`:

```python
def test_build_real_agents_output_works_with_run_pipeline(tmp_path):
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )
    draft = StoryboardDraft(
        scenes=[
            SceneDraft(
                beat_id=beat_id,
                camera="cam",
                subject="subj",
                action="act",
                setting="set",
                required_elements=[],
                duration_weight=1,
            )
            for beat_id in ("setup", "conflict", "climax", "resolution")
        ]
    )
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")
    director_verdict = DirectorVerdict(decision="accept", feedback="ok")

    def fake_parse(*, model, messages, response_format, **kwargs):
        if response_format is Narrative:
            parsed = narrative
        elif response_format is StoryboardDraft:
            parsed = draft
        elif response_format is Prompts:
            parsed = prompts
        elif response_format is DirectorVerdict:
            parsed = director_verdict
        else:
            raise AssertionError(f"unexpected response_format: {response_format}")
        message = SimpleNamespace(parsed=parsed, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    shared_openai_client = MagicMock()
    shared_openai_client.chat.completions.parse.side_effect = fake_parse
    image_data = SimpleNamespace(b64_json="ZmFrZS1pbWFnZS1ieXRlcw==")
    shared_openai_client.images.generate.return_value = SimpleNamespace(data=[image_data])

    shared_gemini_client = MagicMock()
    shared_gemini_client.interactions.create.return_value = SimpleNamespace(
        output_text='{"passed": true, "issues": []}'
    )

    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(
        project_input,
        **build_real_agents(
            openai_api_key="test-key",
            gemini_api_key="test-key",
            nemotron_api_key="test-key",
            openai_client=shared_openai_client,
            gemini_client=shared_gemini_client,
            nemotron_client=shared_openai_client,
            output_dir=tmp_path / "media",
        ),
    )

    assert len(project.scenes) == 4
    assert project.scenes[0].render is not None
    assert project.scenes[0].candidates[-1].consistency_review.passed is True
    assert project.scenes[0].candidates[-1].director_decision.decision == "accept"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_factory.py -v`
Expected: FAIL — `build_real_agents` doesn't accept `nemotron_api_key`/`nemotron_client` yet and returns only 5 keys.

- [ ] **Step 3: Write the implementation**

Replace `src/video_draft_pipeline/agents/factory.py` in full:

```python
from pathlib import Path

from google import genai
from openai import OpenAI

from ..config import ModelConfig
from .gemini_review_agent import GeminiReviewAgent
from .nemotron_director_agent import NemotronDirectorAgent
from .openai_image_agent import OpenAIImageAgent
from .openai_planning_agent import OpenAIPlanningAgent
from .openai_prompt_agent import OpenAIPromptAgent
from .openai_storyboard_agent import OpenAIStoryboardAgent


def build_real_agents(
    openai_api_key: str | None = None,
    gemini_api_key: str | None = None,
    nemotron_api_key: str | None = None,
    output_dir: str | Path = "media",
    model_config: ModelConfig | None = None,
    openai_client: OpenAI | None = None,
    gemini_client: genai.Client | None = None,
    nemotron_client: OpenAI | None = None,
) -> dict[str, object]:
    models = model_config or ModelConfig()
    return {
        "planning_agent": OpenAIPlanningAgent(models.planning_model, api_key=openai_api_key, client=openai_client),
        "storyboard_agent": OpenAIStoryboardAgent(models.storyboard_model, api_key=openai_api_key, client=openai_client),
        "prompt_agent": OpenAIPromptAgent(models.prompt_model, api_key=openai_api_key, client=openai_client),
        "image_agent": OpenAIImageAgent(models.image_model, output_dir=output_dir, api_key=openai_api_key, client=openai_client),
        "review_agent": GeminiReviewAgent(models.review_model, api_key=gemini_api_key, client=gemini_client),
        "director_agent": NemotronDirectorAgent(models.director_model, api_key=nemotron_api_key, client=nemotron_client),
    }
```

In `README.md`, replace the "Environment variables" section's `.env.example` note and code block:

```markdown
## Environment variables

`.env` is **not** auto-loaded — there is no `python-dotenv` dependency. `config.load_api_keys()` reads `os.environ` directly, so export the keys into your shell before running:

```bash
export OPENAI_API_KEY=...      # PowerShell: $env:OPENAI_API_KEY = "..."
export GEMINI_API_KEY=...
export NEMOTRON_API_KEY=...
```

All model access goes through 엘리스's OpenAI-compatible proxy gateway, not the vendors' own endpoints directly. Each real agent resolves its own `base_url` the same way it resolves its API key (explicit constructor arg → env var → SDK default), via these optional per-stage env vars:

```bash
export OPENAI_PLANNING_BASE_URL=...
export OPENAI_STORYBOARD_BASE_URL=...
export OPENAI_PROMPT_BASE_URL=...
export OPENAI_IMAGE_BASE_URL=...
export GEMINI_REVIEW_BASE_URL=...
export NEMOTRON_DIRECTOR_BASE_URL=...
```

`.env.example` lists the key names as a reference. The stub agents do not use these keys yet.
```

Replace the "Real agent injection" section:

```markdown
## Real agent injection

`run_pipeline` accepts `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`, `review_agent`, and `director_agent` — pass an instance of the matching real class to use it for that stage instead of the stub. Any not given fall back to their stub, so the pipeline stays fully offline by default. `VideoRenderAgent` has no real implementation yet and cannot be overridden this way.

The easiest way to inject all six at once is `build_real_agents()`, which constructs them with shared config and returns a dict shaped exactly for `run_pipeline`'s injection parameters:

```python
from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.orchestrator import run_pipeline

run_pipeline(project_input, **build_real_agents(openai_api_key="...", gemini_api_key="...", nemotron_api_key="..."))
```

`build_real_agents` takes its own `model_config: ModelConfig` argument — it builds all 6 real agents from `ModelConfig()` defaults unless you pass one in. If you also want non-default models, pass the *same* `ModelConfig` to both `build_real_agents` and `run_pipeline`, or the two calls won't share model choices and some stages will silently use the wrong model:

```python
from video_draft_pipeline.config import ModelConfig

cfg = ModelConfig(planning_model="openai/gpt-5.4", render_backend="veo-3.1-lite")
run_pipeline(
    project_input,
    model_config=cfg,
    **build_real_agents(openai_api_key="...", gemini_api_key="...", nemotron_api_key="...", model_config=cfg),
)
```

To inject just one or two stages instead of all six, construct that agent directly (OpenAI-backed agents under `video_draft_pipeline.agents.openai_*`, the Gemini-backed reviewer under `video_draft_pipeline.agents.gemini_review_agent`, the Nemotron-backed director under `video_draft_pipeline.agents.nemotron_director_agent`):

```python
from video_draft_pipeline.agents.openai_planning_agent import OpenAIPlanningAgent
from video_draft_pipeline.orchestrator import run_pipeline

run_pipeline(project_input, planning_agent=OpenAIPlanningAgent(api_key="..."))
```

An injected real agent's own `model_name` applies for that stage — `ModelConfig`'s corresponding field on `run_pipeline` is bypassed for any stage you inject (via either path above).
```

Replace `.env.example` in full:

```bash
# Reference only — this file is NOT auto-loaded (no python-dotenv dependency).
# Export these into your shell environment; config.load_api_keys() reads os.environ.
OPENAI_API_KEY=
GEMINI_API_KEY=
NEMOTRON_API_KEY=

# Optional — Elice proxy base URLs, one per stage. Unset means the underlying
# SDK's own default endpoint is used.
OPENAI_PLANNING_BASE_URL=
OPENAI_STORYBOARD_BASE_URL=
OPENAI_PROMPT_BASE_URL=
OPENAI_IMAGE_BASE_URL=
GEMINI_REVIEW_BASE_URL=
NEMOTRON_DIRECTOR_BASE_URL=
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass, full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/factory.py README.md .env.example tests/agents/test_factory.py
git commit -m "feat: add director_agent to build_real_agents, document Elice base_url env vars"
```

---

## Self-Review Notes

- **Spec coverage:** Config layer (Task 1), base class `base_url` support (Task 2), retrofit of 4 OpenAI-family agents + `GeminiReviewAgent` (Task 3), `NemotronDirectorAgent` (Task 4), `DirectorAgentProtocol` + stub `estimate_cost` (Task 5), orchestrator injection + budget guard (Task 6), factory + README + `.env.example` (Task 7) — all spec sections are covered by exactly one task each.
- **Two implementation-safety refinements beyond the spec's literal code samples**, both preserving the approved design's intent without changing any user-facing behavior or requiring re-approval:
  1. `base_url_config_field: str | None = None` (spec showed a bare `base_url_config_field: str` with no default) — without this, Task 2 landing alone would raise `AttributeError` on every existing real-agent construction before Task 3 retrofits them, breaking the "full suite green after every task" invariant every other plan in this project follows.
  2. `api_key_config_field: str = "openai_api_key"` on `BaseOpenAIAgent` (not in the spec's code sample at all) — without this, `NemotronDirectorAgent` (spec-approved to reuse `BaseOpenAIAgent` directly) would silently resolve `OPENAI_API_KEY` instead of `NEMOTRON_API_KEY` when constructed with no explicit `api_key`, contradicting the spec's own statement that `nemotron_api_key` "is now load-bearing" and breaking the "construct with no args, read the right env var" convention every other agent in this codebase follows.
- **Explicitly out of scope, confirmed via grep triage:** the stub agents' own hardcoded default model-name strings (`planning_agent.py`, `storyboard_agent.py`, `prompt_agent.py`, `image_agent.py`, `review_agent.py`, and `director_agent.py`'s `director_name` param) are untouched — the approved spec only changes `ModelConfig` and the 5 real agent classes. Their test files (`test_planning_agent.py`, `test_storyboard_agent.py`, `test_prompt_agent.py`, `test_image_agent.py`, `test_review_agent.py`) are correspondingly untouched. `render_backends`/Veo-related test files matching the grep (`test_selfhosted_backend.py`, `test_veo_backend.py`, `test_video_render_agent.py`) matched only on the coincidental `"gpt-image-2"` fixture string used as an arbitrary `Candidate.generated_by` value, unrelated to `ModelConfig` — also untouched.
- **Placeholder scan:** no "TBD"/"handle appropriately"/"similar to Task N" phrasing anywhere in this plan; every step shows complete, copy-pasteable code.
- **Type consistency:** `base_url_config_field`/`api_key_config_field` names and defaults match exactly between Task 2 (definition) and Tasks 3-4 (usage). `DirectorAgentProtocol.run(scene, review) -> DirectorDecision` (Task 5) matches `NemotronDirectorAgent.run` (Task 4) and `DirectorAgent.run` (unchanged stub) exactly. `build_real_agents`'s `nemotron_api_key`/`nemotron_client` (Task 7) match `NemotronDirectorAgent`'s `api_key`/`client` params (Task 4) via the same threading pattern used for `openai_api_key`/`gemini_api_key`.
