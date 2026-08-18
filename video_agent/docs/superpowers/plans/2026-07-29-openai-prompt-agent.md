# OpenAIPromptAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a real `OpenAIPromptAgent` that turns a `Scene` into `Prompts` via the OpenAI API, coexisting with (not replacing) the existing stub `PromptAgent`.

**Architecture:** One new file, `src/video_draft_pipeline/agents/openai_prompt_agent.py`, exposing `.run(scene) -> Prompts`, matching the stub's shape. `Prompts` is used directly as `response_format` (no throwaway draft type needed — unlike `OpenAIStoryboardAgent`, `Prompts` has no numeric/business-constrained fields). After a successful, non-refused response, `scene.storyboard.required_elements` is deterministically appended to `image_prompt` in Python (never trusted to the model). Key resolution, client injection, and error wrapping follow the same pattern as the prior two real agents, reusing `MissingAPIKeyError` by import.

**Tech Stack:** Python 3.11+, Pydantic v2, `openai` Python SDK (already a runtime dependency), pytest + `unittest.mock`.

## Global Constraints

- The existing stub `src/video_draft_pipeline/agents/prompt_agent.py` and its tests (`tests/agents/test_prompt_agent.py`) are not modified.
- `MissingAPIKeyError` is imported from `video_draft_pipeline.agents.openai_planning_agent`, not redefined.
- `Prompts` (the real domain type from `schema.py`) is used directly as `response_format` — do not introduce a draft/intermediate response type for this agent.
- The file must start with no forward-reference risk: define `PromptAgentError` and any module-level functions in an order where nothing references a name not yet defined at that point (avoid the exact class of bug fixed in `OpenAIStoryboardAgent`'s Task 3 — if in doubt, add `from __future__ import annotations` as the first line; this plan's task order does not require it, but it's a safe default and does not conflict with anything below if the implementer includes it).
- No task may make a real network call or require a real API key. All tests run fully offline (mock the OpenAI SDK client boundary).
- `run_pipeline`/`orchestrator.py` wiring is out of scope (non-goal in the spec, `docs/superpowers/specs/2026-07-29-openai-prompt-agent-design.md`).
- The existing 92 tests must continue to pass unchanged after every task.
- Generated prompt content (system/user prompts) follows the project's Korean-language convention — the prompt must explicitly instruct the model to respond in Korean.

---

### Task 1: Exceptions and fail-fast constructor

**Files:**
- Create: `src/video_draft_pipeline/agents/openai_prompt_agent.py`
- Test: `tests/agents/test_openai_prompt_agent.py`

**Interfaces:**
- Consumes: `video_draft_pipeline.config.load_api_keys() -> ApiKeys` (existing), `video_draft_pipeline.agents.openai_planning_agent.MissingAPIKeyError` (existing, imported not redefined).
- Produces:
  - `class PromptAgentError(Exception)`
  - `class OpenAIPromptAgent.__init__(self, model_name: str = "gpt-5-mini", api_key: str | None = None, client: "OpenAI | None" = None)` — raises `MissingAPIKeyError` if no key resolves; otherwise sets `self.model_name`, `self.api_key`, `self._client`.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_openai_prompt_agent.py`:

```python
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.openai_planning_agent import MissingAPIKeyError
from video_draft_pipeline.agents.openai_prompt_agent import OpenAIPromptAgent


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        OpenAIPromptAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPromptAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPromptAgent(client=MagicMock())

    assert agent.api_key == "env-key"


def test_default_model_name_is_gpt_5_mini(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPromptAgent(client=MagicMock())

    assert agent.model_name == "gpt-5-mini"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPromptAgent(model_name="custom-prompter", client=MagicMock())

    assert agent.model_name == "custom-prompter"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.openai_prompt_agent'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/video_draft_pipeline/agents/openai_prompt_agent.py`:

```python
from openai import OpenAI

from .. import config
from .openai_planning_agent import MissingAPIKeyError


class PromptAgentError(Exception):
    pass


class OpenAIPromptAgent:
    def __init__(
        self,
        model_name: str = "gpt-5-mini",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        resolved_key = api_key or config.load_api_keys().openai_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No OpenAI API key found: pass api_key explicitly or set OPENAI_API_KEY."
            )
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or OpenAI(api_key=resolved_key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (92 existing + 5 new = 97 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_prompt_agent.py tests/agents/test_openai_prompt_agent.py
git commit -m "feat: add OpenAIPromptAgent with fail-fast key resolution"
```

---

### Task 2: Prompt/message builder

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_prompt_agent.py`
- Test: `tests/agents/test_openai_prompt_agent.py`

**Interfaces:**
- Consumes: `video_draft_pipeline.schema.Scene` (`.storyboard: Storyboard`, with `.camera`, `.subject`, `.action`, `.setting`, `.required_elements`) — existing.
- Produces: module-level function `_build_messages(scene: Scene) -> list[dict]` returning `[{"role": "system", "content": str}, {"role": "user", "content": str}]`, consumed by Task 3's `run()`. Also produces a test helper `_scene(required_elements=None) -> Scene` used by this task's and Task 3's tests.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_prompt_agent.py`:

```python
from video_draft_pipeline.agents.openai_prompt_agent import _build_messages
from video_draft_pipeline.schema import Scene, Storyboard


def _scene(required_elements=None):
    return Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6,
        storyboard=Storyboard(
            camera="슬로우 팬, 성벽 따라 이동",
            subject="호박 몬스터 무리",
            action="성벽을 타고 올라옴",
            setting="성 외곽, 야간",
            required_elements=required_elements or [],
        ),
    )


def test_build_messages_has_system_then_user_role():
    messages = _build_messages(_scene())

    assert [m["role"] for m in messages] == ["system", "user"]


def test_build_messages_includes_storyboard_fields():
    messages = _build_messages(_scene())
    user_content = messages[1]["content"]

    assert "슬로우 팬, 성벽 따라 이동" in user_content
    assert "호박 몬스터 무리" in user_content
    assert "성벽을 타고 올라옴" in user_content
    assert "성 외곽, 야간" in user_content


def test_build_messages_system_instructs_korean_output():
    messages = _build_messages(_scene())
    system_content = messages[0]["content"]

    assert "Korean" in system_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v -k build_messages`
Expected: FAIL with `ImportError: cannot import name '_build_messages'`

- [ ] **Step 3: Write the minimal implementation**

In `src/video_draft_pipeline/agents/openai_prompt_agent.py`, change the top import line:

```python
from .. import config
```

to:

```python
from .. import config
from ..schema import Prompts, Scene
```

Then add this function (below the imports, above `PromptAgentError`):

```python
def _build_messages(scene: Scene) -> list[dict]:
    sb = scene.storyboard
    system = (
        "You are a prompt engineer generating an image generation prompt and a "
        "video motion prompt for a single scene of a game marketing video. "
        "image_prompt should describe the visual content: setting, subject, "
        "action, and camera framing. video_motion_prompt should describe only "
        "the camera movement and action, not static visual details. Respond "
        "in Korean, matching the language of the input."
    )
    user = (
        f"Camera: {sb.camera}\n"
        f"Subject: {sb.subject}\n"
        f"Action: {sb.action}\n"
        f"Setting: {sb.setting}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

(`Prompts` is imported now even though it is not yet used by this function — it is needed by Task 3.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (92 existing + 8 new = 100 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_prompt_agent.py tests/agents/test_openai_prompt_agent.py
git commit -m "feat: add OpenAIPromptAgent prompt/message builder"
```

---

### Task 3: `run()` — Structured Outputs call and required-elements enforcement

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_prompt_agent.py`
- Test: `tests/agents/test_openai_prompt_agent.py`

**Interfaces:**
- Consumes: `_build_messages` (Task 2), `self.model_name`, `self._client` (Task 1), `Prompts` (Task 2's import), `video_draft_pipeline.schema.Scene`.
- Produces: `OpenAIPromptAgent.run(self, scene: Scene) -> Prompts`. Raises `PromptAgentError` if the SDK call fails or the model refuses.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_prompt_agent.py`:

```python
from types import SimpleNamespace

from video_draft_pipeline.agents.openai_prompt_agent import PromptAgentError
from video_draft_pipeline.schema import Prompts


def _fake_completion(parsed=None, refusal=None) -> SimpleNamespace:
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def test_run_appends_required_elements_when_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    scene = _scene(required_elements=["이벤트 로고 노출"])
    parsed = Prompts(image_prompt="야간 성벽, 몬스터 무리", video_motion_prompt="슬로우 팬")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(parsed=parsed)
    agent = OpenAIPromptAgent(client=client)

    result = agent.run(scene)

    assert result.image_prompt == "야간 성벽, 몬스터 무리, 이벤트 로고 노출"
    assert result.video_motion_prompt == "슬로우 팬"


def test_run_leaves_image_prompt_unmodified_when_no_required_elements(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    scene = _scene(required_elements=[])
    parsed = Prompts(image_prompt="야간 성벽, 몬스터 무리", video_motion_prompt="슬로우 팬")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(parsed=parsed)
    agent = OpenAIPromptAgent(client=client)

    result = agent.run(scene)

    assert result.image_prompt == "야간 성벽, 몬스터 무리"


def test_run_calls_sdk_with_expected_model_and_response_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    scene = _scene()
    parsed = Prompts(image_prompt="p", video_motion_prompt="m")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(parsed=parsed)
    agent = OpenAIPromptAgent(model_name="custom-prompter", client=client)

    agent.run(scene)

    _, kwargs = client.chat.completions.parse.call_args
    assert kwargs["model"] == "custom-prompter"
    assert kwargs["response_format"] is Prompts
    assert kwargs["messages"] == _build_messages(scene)


def test_run_raises_on_refusal(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    scene = _scene()
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(
        parsed=None, refusal="cannot help with that"
    )
    agent = OpenAIPromptAgent(client=client)

    with pytest.raises(PromptAgentError):
        agent.run(scene)


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    scene = _scene()
    client = MagicMock()
    client.chat.completions.parse.side_effect = RuntimeError("boom")
    agent = OpenAIPromptAgent(client=client)

    with pytest.raises(PromptAgentError):
        agent.run(scene)
```

(`_scene` was already added in Task 2's test additions — do not redefine it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v -k test_run_`
Expected: FAIL with `AttributeError: 'OpenAIPromptAgent' object has no attribute 'run'`

- [ ] **Step 3: Write the minimal implementation**

In `src/video_draft_pipeline/agents/openai_prompt_agent.py`, add a `run` method to `OpenAIPromptAgent` (after `__init__`):

```python
    def run(self, scene: Scene) -> Prompts:
        try:
            completion = self._client.chat.completions.parse(
                model=self.model_name,
                messages=_build_messages(scene),
                response_format=Prompts,
            )
        except Exception as exc:
            raise PromptAgentError(f"OpenAI prompt call failed: {exc}") from exc
        message = completion.choices[0].message
        if message.parsed is None:
            raise PromptAgentError(
                f"OpenAI prompt call returned no prompts: {message.refusal or 'empty response'}"
            )
        image_prompt = message.parsed.image_prompt
        if scene.storyboard.required_elements:
            image_prompt = f"{image_prompt}, {', '.join(scene.storyboard.required_elements)}"
        return Prompts(
            image_prompt=image_prompt,
            video_motion_prompt=message.parsed.video_motion_prompt,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (92 existing + 13 new = 105 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_prompt_agent.py tests/agents/test_openai_prompt_agent.py
git commit -m "feat: implement OpenAIPromptAgent.run with required-elements enforcement"
```

---

## Self-Review Notes

- **Spec coverage:** Goals (real agent producing `Prompts`, guaranteed required-elements presence, fail-loud on refusal/SDK failure, stub untouched) → Tasks 1, 3. Non-goals (no orchestrator wiring, no live test, no other agents, no shared-plumbing extraction, no retry-loop change) → untouched, not in any task. Architecture (new file, `Prompts` used directly as `response_format`, no draft type, `MissingAPIKeyError` reused) → Task 1, 3. Key resolution → Task 1. Required-elements enforcement (image_prompt only, post-processing not validation) → Task 3. Error handling (one exception type, two failure modes) → Task 3. Testing (key-free, both required-elements branches, refusal, SDK exception) → Tasks 1-3.
- **Placeholder scan:** no TBD/TODO markers; every step has full, final code.
- **Type consistency:** `_build_messages(scene)` signature in Task 2 matches its call in Task 3. `_scene(required_elements=None)` helper defined once in Task 2, reused (not redefined) in Task 3. `PromptAgentError` name matches between Task 1's definition and Task 3's raises. `MissingAPIKeyError` import path matches the location established in the two prior plans.
