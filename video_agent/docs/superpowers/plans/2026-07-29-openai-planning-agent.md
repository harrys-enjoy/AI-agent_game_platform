# OpenAIPlanningAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a real `OpenAIPlanningAgent` that produces a `Narrative` from a `ProjectInput` via the OpenAI API, coexisting with (not replacing) the existing stub `PlanningAgent`.

**Architecture:** One new file, `src/video_draft_pipeline/agents/openai_planning_agent.py`, exposing the same `.run(project_input) -> Narrative` shape as the stub. Key resolution happens fail-fast in `__init__` (explicit arg → `config.load_api_keys()` → raise). The OpenAI client is injectable via an optional constructor param so tests can mock the SDK boundary without a real key or network call. Uses the OpenAI SDK's Structured Outputs (`response_format=Narrative`) so the API response is already a validated `Narrative` instance — no manual JSON parsing.

**Tech Stack:** Python 3.11+, Pydantic v2, `openai` Python SDK, pytest + `unittest.mock`.

## Global Constraints

- Python `>=3.11`, `pydantic>=2.5` (already in `pyproject.toml` — do not change).
- New runtime dependency `openai` goes in `[project.dependencies]`, **not** `[project.optional-dependencies].dev`.
- The existing stub `src/video_draft_pipeline/agents/planning_agent.py` and its tests (`tests/agents/test_planning_agent.py`) are not modified.
- No task may make a real network call or require a real API key. All tests run fully offline (mock the OpenAI SDK client boundary).
- `run_pipeline`/`orchestrator.py` wiring to select between stub and real agent is out of scope (explicit non-goal in the spec, `docs/superpowers/specs/2026-07-28-openai-planning-agent-design.md`).
- The existing 58 tests must continue to pass unchanged after every task.

---

### Task 1: Add `openai` runtime dependency

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `openai` package importable as `from openai import OpenAI` for later tasks.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, change:

```toml
dependencies = [
    "pydantic>=2.5",
]
```

to:

```toml
dependencies = [
    "pydantic>=2.5",
    "openai>=1.50",
]
```

- [ ] **Step 2: Install it**

Run: `pip install -e ".[dev]"`
Expected: install succeeds, `openai` appears in the installed package list.

- [ ] **Step 3: Verify the import works**

Run: `python -c "from openai import OpenAI; print('ok')"`
Expected: prints `ok` with no error.

- [ ] **Step 4: Run the full existing test suite to confirm nothing broke**

Run: `pytest -q`
Expected: all existing tests still pass (58 passed).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: add openai SDK as a runtime dependency"
```

---

### Task 2: Exceptions and fail-fast constructor

**Files:**
- Create: `src/video_draft_pipeline/agents/openai_planning_agent.py`
- Test: `tests/agents/test_openai_planning_agent.py`

**Interfaces:**
- Consumes: `video_draft_pipeline.config.load_api_keys() -> ApiKeys` where `ApiKeys.openai_api_key: str | None` (existing, `src/video_draft_pipeline/config.py`).
- Produces:
  - `class MissingAPIKeyError(Exception)`
  - `class PlanningAgentError(Exception)`
  - `class OpenAIPlanningAgent.__init__(self, model_name: str = "gpt-5.4", api_key: str | None = None, client: "OpenAI | None" = None)` — raises `MissingAPIKeyError` if no key resolves; otherwise sets `self.model_name`, `self.api_key`, `self._client` (the injected `client` if given, else a real `OpenAI(api_key=...)`).

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_openai_planning_agent.py`:

```python
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.openai_planning_agent import (
    MissingAPIKeyError,
    OpenAIPlanningAgent,
)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        OpenAIPlanningAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPlanningAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPlanningAgent(client=MagicMock())

    assert agent.api_key == "env-key"


def test_default_model_name_is_gpt_5_4(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPlanningAgent(client=MagicMock())

    assert agent.model_name == "gpt-5.4"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPlanningAgent(model_name="custom-planner", client=MagicMock())

    assert agent.model_name == "custom-planner"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_planning_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.openai_planning_agent'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/video_draft_pipeline/agents/openai_planning_agent.py`:

```python
from openai import OpenAI

from .. import config


class MissingAPIKeyError(Exception):
    pass


class PlanningAgentError(Exception):
    pass


class OpenAIPlanningAgent:
    def __init__(
        self,
        model_name: str = "gpt-5.4",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        resolved_key = api_key or config.load_api_keys().openai_api_key
        if resolved_key is None:
            raise MissingAPIKeyError(
                "No OpenAI API key found: pass api_key explicitly or set OPENAI_API_KEY."
            )
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or OpenAI(api_key=resolved_key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_planning_agent.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (58 existing + 5 new = 63 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_planning_agent.py tests/agents/test_openai_planning_agent.py
git commit -m "feat: add OpenAIPlanningAgent with fail-fast key resolution"
```

---

### Task 3: Prompt/message builder

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_planning_agent.py`
- Test: `tests/agents/test_openai_planning_agent.py`

**Interfaces:**
- Consumes: `video_draft_pipeline.schema.ProjectInput` fields `.preset`, `.scene_type`, `.brief`, `.brand_requirements` (existing, `src/video_draft_pipeline/schema.py`).
- Produces: module-level function `_build_messages(project_input: ProjectInput) -> list[dict]` returning `[{"role": "system", "content": str}, {"role": "user", "content": str}]`, consumed by Task 4's `run()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_planning_agent.py`:

```python
from video_draft_pipeline.agents.openai_planning_agent import _build_messages
from video_draft_pipeline.schema import ProjectInput


def test_build_messages_has_system_then_user_role():
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=15, brief="신규 캐릭터 공개"
    )

    messages = _build_messages(project_input)

    assert [m["role"] for m in messages] == ["system", "user"]


def test_build_messages_user_content_includes_input_fields():
    project_input = ProjectInput(
        preset="공개",
        scene_type="인게임",
        duration_sec=15,
        brief="신규 캐릭터 공개",
        brand_requirements=["로고 노출"],
    )

    messages = _build_messages(project_input)
    user_content = messages[1]["content"]

    assert "신규 캐릭터 공개" in user_content
    assert "공개" in user_content
    assert "인게임" in user_content
    assert "로고 노출" in user_content


def test_build_messages_handles_empty_brand_requirements():
    project_input = ProjectInput(
        preset="이벤트", scene_type="스튜디오", duration_sec=10, brief="브리프"
    )

    messages = _build_messages(project_input)

    assert messages[1]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_planning_agent.py -v -k build_messages`
Expected: FAIL with `ImportError: cannot import name '_build_messages'`

- [ ] **Step 3: Write the minimal implementation**

In `src/video_draft_pipeline/agents/openai_planning_agent.py`, add (below the imports, above `MissingAPIKeyError`):

```python
from .. import config
from ..schema import Narrative, ProjectInput


def _build_messages(project_input: ProjectInput) -> list[dict]:
    system = (
        "You are a creative director generating a 4-beat narrative for a game "
        "marketing video draft. Produce exactly one beat for each of: "
        "setup, conflict, climax, resolution."
    )
    requirements = ", ".join(project_input.brand_requirements) or "none"
    user = (
        f"Preset: {project_input.preset}\n"
        f"Scene type: {project_input.scene_type}\n"
        f"Brief: {project_input.brief}\n"
        f"Brand requirements: {requirements}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

(Replace the existing `from .. import config` import line at the top of the file with the two-line import block above — `Narrative` and `ProjectInput` are needed now and by Task 4.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_planning_agent.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (58 existing + 8 new = 66 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_planning_agent.py tests/agents/test_openai_planning_agent.py
git commit -m "feat: add OpenAIPlanningAgent prompt/message builder"
```

---

### Task 4: `run()` — Structured Outputs call and error wrapping

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_planning_agent.py`
- Test: `tests/agents/test_openai_planning_agent.py`

**Interfaces:**
- Consumes: `_build_messages(project_input) -> list[dict]` (Task 3), `self.model_name`, `self._client` (Task 2), `video_draft_pipeline.schema.Narrative` (existing).
- Produces: `OpenAIPlanningAgent.run(self, project_input: ProjectInput) -> Narrative`. Raises `PlanningAgentError` if the underlying SDK call raises anything.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_planning_agent.py`:

```python
from types import SimpleNamespace

from video_draft_pipeline.agents.openai_planning_agent import PlanningAgentError
from video_draft_pipeline.schema import Beat, Narrative


def _fake_completion(narrative: Narrative) -> SimpleNamespace:
    message = SimpleNamespace(parsed=narrative)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def test_run_returns_parsed_narrative(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(narrative)
    agent = OpenAIPlanningAgent(client=client)
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=15, brief="브리프"
    )

    result = agent.run(project_input)

    assert result == narrative


def test_run_calls_sdk_with_expected_model_and_response_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(narrative)
    agent = OpenAIPlanningAgent(model_name="custom-planner", client=client)
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=15, brief="브리프"
    )

    agent.run(project_input)

    _, kwargs = client.chat.completions.parse.call_args
    assert kwargs["model"] == "custom-planner"
    assert kwargs["response_format"] is Narrative
    assert kwargs["messages"] == _build_messages(project_input)


def test_run_wraps_sdk_exception_as_planning_agent_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.side_effect = RuntimeError("boom")
    agent = OpenAIPlanningAgent(client=client)
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=15, brief="브리프"
    )

    with pytest.raises(PlanningAgentError):
        agent.run(project_input)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_planning_agent.py -v -k test_run_`
Expected: FAIL with `AttributeError: 'OpenAIPlanningAgent' object has no attribute 'run'`

- [ ] **Step 3: Write the minimal implementation**

In `src/video_draft_pipeline/agents/openai_planning_agent.py`, add a `run` method to `OpenAIPlanningAgent` (after `__init__`):

```python
    def run(self, project_input: ProjectInput) -> Narrative:
        try:
            completion = self._client.chat.completions.parse(
                model=self.model_name,
                messages=_build_messages(project_input),
                response_format=Narrative,
            )
        except Exception as exc:
            raise PlanningAgentError(f"OpenAI planning call failed: {exc}") from exc
        return completion.choices[0].message.parsed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_planning_agent.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (58 existing + 11 new = 69 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_planning_agent.py tests/agents/test_openai_planning_agent.py
git commit -m "feat: implement OpenAIPlanningAgent.run via Structured Outputs"
```

---

## Self-Review Notes

- **Spec coverage:** Goals (real agent producing `Narrative`, coexists with stub, fail-fast key error) → Tasks 2–4. Non-goals (no orchestrator wiring, no live smoke test) → untouched, not in any task. Architecture (new file, same class shape as spec skeleton) → Task 2–4. Key resolution order → Task 2. Structured output via `response_format=Narrative` → Task 4. Error handling wrapping into `PlanningAgentError` → Task 4. Dependencies (`openai` in runtime deps) → Task 1. Testing (key-free unit tests: key-resolution error, request shape, error wrapping) → Tasks 2–4.
- **Placeholder scan:** no TBD/TODO markers; every step has full code or an exact runnable command.
- **Type consistency:** `client: OpenAI | None` in Task 2 matches the `MagicMock()`-injected `client` used in every later test; `_build_messages` signature in Task 3 matches its usage in Task 4's `run()`; `PlanningAgentError`/`MissingAPIKeyError` names match between Task 2's definition and later imports.
