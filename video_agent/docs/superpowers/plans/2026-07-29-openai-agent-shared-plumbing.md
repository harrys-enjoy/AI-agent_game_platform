# Shared OpenAI-Agent Plumbing Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the duplicated constructor and SDK-call/refusal-check logic from `OpenAIPlanningAgent`, `OpenAIStoryboardAgent`, and `OpenAIPromptAgent` into a shared `BaseOpenAIAgent`, fixing two latent bugs (an unguarded empty-`choices` access, and no offline guard against a future `response_format` type breaking OpenAI's strict schema) as part of the same change.

**Architecture:** One new file, `src/video_draft_pipeline/agents/openai_agent_base.py`, holding `MissingAPIKeyError` (relocated) and `BaseOpenAIAgent` (key resolution + a `_structured_completion` helper). Each of the three existing agents becomes a thin subclass: its own `XAgentError` stays, set as a class attribute `error_cls`; its `__init__` becomes a one-line `super().__init__(...)` call; its `run()` calls `self._structured_completion(messages, ResponseFormatType)` and keeps only its own agent-specific post-processing. A new test-only helper, `tests/agents/_schema_guard.py`, offline-verifies that a `response_format` type's JSON schema doesn't carry any keyword OpenAI's strict Structured Outputs subset rejects — the exact class of bug `OpenAIStoryboardAgent` shipped with and only caught in human review.

**Tech Stack:** Python 3.11+, Pydantic v2, `openai` Python SDK, pytest + `unittest.mock`.

## Global Constraints

- No agent's public interface changes: `.run(...)` signatures, return types, and exception class names/behavior are identical before and after this refactor.
- `PlanningAgentError`, `StoryboardAgentError`, `PromptAgentError` stay distinct — do not unify into one exception type.
- No re-export shim in the final state (after Task 4): `openai_planning_agent.py` does not re-export `MissingAPIKeyError`, and every file that imports it (including the two other agents and all three existing test files) imports it directly from `openai_agent_base`. **Amendment (discovered mid-Task-2):** the original plan did not account for Tasks 3-4 still importing `MissingAPIKeyError` from `openai_planning_agent` until their own migration lands, so removing it cleanly in Task 2 alone breaks `test_openai_storyboard_agent.py`/`test_openai_prompt_agent.py` collection and contradicts Task 2's own "full suite passes" step. Resolution (human-approved): Task 2 keeps a temporary re-export line (`from .openai_agent_base import BaseOpenAIAgent, MissingAPIKeyError`) so the full suite stays green after every task; Task 4 removes that re-export as its final step once storyboard's and prompt's own imports have been corrected, so the constraint above still holds for the plan's actual end state.
- Every existing test assertion stays exactly as it is today. The only permitted per-file edits to the three existing test files are: (1) the `MissingAPIKeyError` import path correction, and (2) adding the new schema-guard test(s) for that file's `response_format` type(s). No existing test's body, name, or assertions change.
- The three existing test files must show the exact same pass/fail behavior for every pre-existing test after the refactor as before it — this refactor changes internal implementation only, never observable behavior.
- New shared code introduces no new runtime dependency (no dependency change to `pyproject.toml`).

---

### Task 1: `BaseOpenAIAgent`, `MissingAPIKeyError`, and the schema guard

**Files:**
- Create: `src/video_draft_pipeline/agents/openai_agent_base.py`
- Test: `tests/agents/test_openai_agent_base.py`
- Create: `tests/agents/_schema_guard.py`
- Test: `tests/agents/test_schema_guard.py`

**Interfaces:**
- Consumes: `video_draft_pipeline.config.load_api_keys() -> ApiKeys` (existing).
- Produces:
  - `class MissingAPIKeyError(Exception)`
  - `class BaseOpenAIAgent`: class attribute `error_cls: type[Exception]` (subclasses must set it); `__init__(self, model_name: str, api_key: str | None = None, client: "OpenAI | None" = None)` — raises `MissingAPIKeyError` if no key resolves; sets `self.model_name`, `self.api_key`, `self._client`. Method `_structured_completion(self, messages: list[dict], response_format: type) -> object` — calls `self._client.chat.completions.parse(model=self.model_name, messages=messages, response_format=response_format)`; wraps any SDK exception, an empty `choices` list, or a refusal (`parsed is None`) into `self.error_cls`; on success returns `completion.choices[0].message.parsed` directly.
  - `assert_strict_schema_safe(model: type) -> None` in `tests/agents/_schema_guard.py` — raises `AssertionError` if `model.model_json_schema()` contains, anywhere (including nested `$defs`), any of: `exclusiveMinimum`, `exclusiveMaximum`, `minimum`, `maximum`, `minLength`, `maxLength`, `pattern`, `format`, `multipleOf`. Consumed by Tasks 2-4.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_openai_agent_base.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.openai_agent_base import BaseOpenAIAgent, MissingAPIKeyError


class _DummyError(Exception):
    pass


class _DummyAgent(BaseOpenAIAgent):
    error_cls = _DummyError


def _fake_completion(choices=None) -> SimpleNamespace:
    return SimpleNamespace(choices=choices if choices is not None else [])


def _fake_choice(parsed=None, refusal=None) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=refusal))


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        _DummyAgent(model_name="dummy-model")


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", client=MagicMock())

    assert agent.api_key == "env-key"


def test_model_name_stored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = _DummyAgent(model_name="dummy-model", client=MagicMock())

    assert agent.model_name == "dummy-model"


def test_structured_completion_returns_parsed_result(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(
        choices=[_fake_choice(parsed="the-result")]
    )
    agent = _DummyAgent(model_name="dummy-model", client=client)

    result = agent._structured_completion(
        messages=[{"role": "user", "content": "hi"}], response_format=str
    )

    assert result == "the-result"


def test_structured_completion_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.side_effect = RuntimeError("boom")
    agent = _DummyAgent(model_name="dummy-model", client=client)

    with pytest.raises(_DummyError):
        agent._structured_completion(messages=[], response_format=str)


def test_structured_completion_raises_on_empty_choices(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(choices=[])
    agent = _DummyAgent(model_name="dummy-model", client=client)

    with pytest.raises(_DummyError):
        agent._structured_completion(messages=[], response_format=str)


def test_structured_completion_raises_on_refusal(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(
        choices=[_fake_choice(parsed=None, refusal="cannot help")]
    )
    agent = _DummyAgent(model_name="dummy-model", client=client)

    with pytest.raises(_DummyError):
        agent._structured_completion(messages=[], response_format=str)
```

Create `tests/agents/test_schema_guard.py`:

```python
import pytest
from pydantic import BaseModel, Field

from tests.agents._schema_guard import assert_strict_schema_safe


class _SafeModel(BaseModel):
    name: str
    count: int


class _UnsafeModel(BaseModel):
    weight: float = Field(gt=0)


def test_assert_strict_schema_safe_passes_for_unconstrained_model():
    assert_strict_schema_safe(_SafeModel)


def test_assert_strict_schema_safe_fails_for_gt_constrained_model():
    with pytest.raises(AssertionError):
        assert_strict_schema_safe(_UnsafeModel)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_agent_base.py tests/agents/test_schema_guard.py -v`
Expected: FAIL — `test_openai_agent_base.py` fails to collect with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.openai_agent_base'`; `test_schema_guard.py` fails to collect with `ModuleNotFoundError: No module named 'tests.agents._schema_guard'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/video_draft_pipeline/agents/openai_agent_base.py`:

```python
from openai import OpenAI
from pydantic import BaseModel

from .. import config


class MissingAPIKeyError(Exception):
    pass


class BaseOpenAIAgent:
    error_cls: type[Exception]

    def __init__(
        self,
        model_name: str,
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

    def _structured_completion(
        self, messages: list[dict], response_format: type[BaseModel]
    ) -> BaseModel:
        try:
            completion = self._client.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                response_format=response_format,
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

Create `tests/agents/_schema_guard.py`:

```python
_UNSUPPORTED_STRICT_KEYWORDS = {
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "multipleOf",
}


def assert_strict_schema_safe(model: type) -> None:
    _check_node(model.model_json_schema())


def _check_node(node) -> None:
    if isinstance(node, dict):
        found = _UNSUPPORTED_STRICT_KEYWORDS & node.keys()
        if found:
            raise AssertionError(
                f"Schema node contains unsupported strict-mode keyword(s) {sorted(found)}: {node}"
            )
        for value in node.values():
            _check_node(value)
    elif isinstance(node, list):
        for item in node:
            _check_node(item)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_agent_base.py tests/agents/test_schema_guard.py -v`
Expected: PASS (10 passed — 8 in `test_openai_agent_base.py`, 2 in `test_schema_guard.py`)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (105 existing + 10 new = 115 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_agent_base.py tests/agents/test_openai_agent_base.py tests/agents/_schema_guard.py tests/agents/test_schema_guard.py
git commit -m "feat: add BaseOpenAIAgent and offline strict-schema guard"
```

---

### Task 2: Migrate `OpenAIPlanningAgent`

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_planning_agent.py`
- Modify: `tests/agents/test_openai_planning_agent.py`

**Interfaces:**
- Consumes: `BaseOpenAIAgent`, `MissingAPIKeyError` (Task 1, from `..agents.openai_agent_base`), `assert_strict_schema_safe` (Task 1, from `tests.agents._schema_guard`).
- Produces: `OpenAIPlanningAgent` now subclasses `BaseOpenAIAgent` with `error_cls = PlanningAgentError`; `.run(project_input) -> Narrative` unchanged in signature/behavior.

- [ ] **Step 1: Fix the test file's import and add the schema-guard test**

In `tests/agents/test_openai_planning_agent.py`, replace lines 6-12:

```python
from video_draft_pipeline.agents.openai_planning_agent import (
    MissingAPIKeyError,
    OpenAIPlanningAgent,
    PlanningAgentError,
    _build_messages,
)
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput
```

with:

```python
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.agents.openai_planning_agent import (
    OpenAIPlanningAgent,
    PlanningAgentError,
    _build_messages,
)
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput
from tests.agents._schema_guard import assert_strict_schema_safe
```

Then add this test anywhere in the file (e.g. at the end):

```python
def test_narrative_response_format_is_strict_schema_safe():
    assert_strict_schema_safe(Narrative)
```

- [ ] **Step 2: Run tests to verify the expected failure**

Run: `pytest tests/agents/test_openai_planning_agent.py -v`
Expected: `test_missing_key_raises` FAILS with `Failed: DID NOT RAISE <class 'video_draft_pipeline.agents.openai_agent_base.MissingAPIKeyError'>` (the code still raises the old, separately-defined `openai_planning_agent.MissingAPIKeyError` at this point — a different class object). All other tests, including the new `test_narrative_response_format_is_strict_schema_safe`, PASS already (they don't depend on this migration).

- [ ] **Step 3: Migrate the source file**

Replace the entire contents of `src/video_draft_pipeline/agents/openai_planning_agent.py` with:

```python
from openai import OpenAI

from ..schema import Narrative, ProjectInput
from .openai_agent_base import BaseOpenAIAgent


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


class PlanningAgentError(Exception):
    pass


class OpenAIPlanningAgent(BaseOpenAIAgent):
    error_cls = PlanningAgentError

    def __init__(
        self,
        model_name: str = "gpt-5.4",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        super().__init__(model_name, api_key, client)

    def run(self, project_input: ProjectInput) -> Narrative:
        return self._structured_completion(_build_messages(project_input), Narrative)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_planning_agent.py -v`
Expected: PASS (12 passed — 11 pre-existing + 1 new schema-guard test)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (115 existing + 1 new = 116 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_planning_agent.py tests/agents/test_openai_planning_agent.py
git commit -m "refactor: migrate OpenAIPlanningAgent onto BaseOpenAIAgent"
```

---

### Task 3: Migrate `OpenAIStoryboardAgent`

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_storyboard_agent.py`
- Modify: `tests/agents/test_openai_storyboard_agent.py`

**Interfaces:**
- Consumes: `BaseOpenAIAgent`, `MissingAPIKeyError` (Task 1), `assert_strict_schema_safe` (Task 1).
- Produces: `OpenAIStoryboardAgent` now subclasses `BaseOpenAIAgent` with `error_cls = StoryboardAgentError`; `.run(narrative, project_input) -> list[Scene]` unchanged in signature/behavior.

- [ ] **Step 1: Fix the test file's import and add the schema-guard tests**

In `tests/agents/test_openai_storyboard_agent.py`, replace line 6:

```python
from video_draft_pipeline.agents.openai_planning_agent import MissingAPIKeyError
```

with:

```python
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from tests.agents._schema_guard import assert_strict_schema_safe
```

Then add these tests anywhere in the file (e.g. at the end):

```python
def test_scene_draft_response_format_is_strict_schema_safe():
    assert_strict_schema_safe(SceneDraft)


def test_storyboard_draft_response_format_is_strict_schema_safe():
    assert_strict_schema_safe(StoryboardDraft)
```

(`SceneDraft` and `StoryboardDraft` are already imported in this file's existing import block.)

- [ ] **Step 2: Run tests to verify the expected failure**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v`
Expected: `test_missing_key_raises` FAILS with `Failed: DID NOT RAISE <class 'video_draft_pipeline.agents.openai_agent_base.MissingAPIKeyError'>` (same reason as Task 2). All other tests, including the two new schema-guard tests, PASS already.

- [ ] **Step 3: Migrate the source file**

Replace the entire contents of `src/video_draft_pipeline/agents/openai_storyboard_agent.py` with:

```python
from __future__ import annotations

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from ..schema import BeatId, Narrative, ProjectInput, Scene, Storyboard
from .openai_agent_base import BaseOpenAIAgent


def _build_messages(narrative: Narrative, project_input: ProjectInput) -> list[dict]:
    system = (
        "You are a creative director generating a shot-by-shot storyboard for a "
        "game marketing video draft. For each beat provided, produce one scene: "
        "a camera direction, the subject, the action, the setting, any required "
        "on-screen elements, and a duration_weight expressing how much relative "
        "screen time this beat deserves compared to the others (for example, a "
        "climax beat might deserve more weight than a setup beat). Respond in "
        "Korean, matching the language of the input."
    )
    beats_description = "\n".join(
        f"- {beat.beat_id}: {beat.description} (tone: {beat.tone})"
        for beat in narrative.beats
    )
    user = (
        f"Preset: {project_input.preset}\n"
        f"Scene type: {project_input.scene_type}\n"
        f"Brief: {project_input.brief}\n"
        f"Beats:\n{beats_description}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _drafts_to_scenes(drafts: list[SceneDraft], project_input: ProjectInput) -> list[Scene]:
    total_weight = sum(draft.duration_weight for draft in drafts)
    n = len(drafts)
    scenes: list[Scene] = []
    running = 0.0
    for i, draft in enumerate(drafts):
        if i < n - 1:
            duration = project_input.duration_sec * draft.duration_weight / total_weight
            running += duration
        else:
            duration = project_input.duration_sec - running
        required_elements = (
            list(project_input.brand_requirements)
            if draft.beat_id == "resolution"
            else []
        )
        scenes.append(
            Scene(
                scene_id=f"scene_{i + 1:02d}",
                beat_id=draft.beat_id,
                order=i + 1,
                duration_sec=duration,
                storyboard=Storyboard(
                    camera=draft.camera,
                    subject=draft.subject,
                    action=draft.action,
                    setting=draft.setting,
                    required_elements=required_elements,
                ),
            )
        )
    return scenes


class StoryboardAgentError(Exception):
    pass


class SceneDraft(BaseModel):
    beat_id: BeatId
    camera: str
    subject: str
    action: str
    setting: str
    required_elements: list[str]
    duration_weight: float


class StoryboardDraft(BaseModel):
    scenes: list[SceneDraft]


class OpenAIStoryboardAgent(BaseOpenAIAgent):
    error_cls = StoryboardAgentError

    def __init__(
        self,
        model_name: str = "gpt-5.4",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        super().__init__(model_name, api_key, client)

    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]:
        if not narrative.beats:
            raise StoryboardAgentError("Narrative has no beats; cannot build a storyboard.")
        draft = self._structured_completion(
            _build_messages(narrative, project_input), StoryboardDraft
        )
        draft_beat_ids = [scene.beat_id for scene in draft.scenes]
        expected_beat_ids = [beat.beat_id for beat in narrative.beats]
        if draft_beat_ids != expected_beat_ids:
            raise StoryboardAgentError(
                f"OpenAI storyboard response beats {draft_beat_ids} do not match "
                f"narrative beats {expected_beat_ids}"
            )
        if any(scene.duration_weight <= 0 for scene in draft.scenes):
            raise StoryboardAgentError(
                "OpenAI storyboard response contained a non-positive duration_weight"
            )
        try:
            return _drafts_to_scenes(draft.scenes, project_input)
        except ValidationError as exc:
            raise StoryboardAgentError(
                f"OpenAI storyboard produced unusable durations: {exc}"
            ) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v`
Expected: PASS (23 passed — 21 pre-existing + 2 new schema-guard tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (116 existing + 2 new = 118 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_storyboard_agent.py tests/agents/test_openai_storyboard_agent.py
git commit -m "refactor: migrate OpenAIStoryboardAgent onto BaseOpenAIAgent"
```

---

### Task 4: Migrate `OpenAIPromptAgent`

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_prompt_agent.py`
- Modify: `tests/agents/test_openai_prompt_agent.py`
- Modify: `src/video_draft_pipeline/agents/openai_planning_agent.py` (Step 7 only — removes the temporary re-export added in Task 2, see the Global Constraints amendment)

**Interfaces:**
- Consumes: `BaseOpenAIAgent`, `MissingAPIKeyError` (Task 1), `assert_strict_schema_safe` (Task 1).
- Produces: `OpenAIPromptAgent` now subclasses `BaseOpenAIAgent` with `error_cls = PromptAgentError`; `.run(scene) -> Prompts` unchanged in signature/behavior. Also: `openai_planning_agent.py` no longer re-exports `MissingAPIKeyError` — the plan's no-shim constraint now holds in the plan's final state, since by this point Tasks 2-4 have all corrected their own `MissingAPIKeyError` import to `openai_agent_base`.

- [ ] **Step 1: Fix the test file's import and add the schema-guard test**

In `tests/agents/test_openai_prompt_agent.py`, replace line 6:

```python
from video_draft_pipeline.agents.openai_planning_agent import MissingAPIKeyError
```

with:

```python
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from tests.agents._schema_guard import assert_strict_schema_safe
```

Then add this test anywhere in the file (e.g. at the end):

```python
def test_prompts_response_format_is_strict_schema_safe():
    assert_strict_schema_safe(Prompts)
```

(`Prompts` is already imported in this file's existing import block.)

- [ ] **Step 2: Run tests to verify the expected failure**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v`
Expected: `test_missing_key_raises` FAILS with `Failed: DID NOT RAISE <class 'video_draft_pipeline.agents.openai_agent_base.MissingAPIKeyError'>` (same reason as Tasks 2-3). All other tests, including the new schema-guard test, PASS already.

- [ ] **Step 3: Migrate the source file**

Replace the entire contents of `src/video_draft_pipeline/agents/openai_prompt_agent.py` with:

```python
from openai import OpenAI

from ..schema import Prompts, Scene
from .openai_agent_base import BaseOpenAIAgent


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


class PromptAgentError(Exception):
    pass


class OpenAIPromptAgent(BaseOpenAIAgent):
    error_cls = PromptAgentError

    def __init__(
        self,
        model_name: str = "gpt-5-mini",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        super().__init__(model_name, api_key, client)

    def run(self, scene: Scene) -> Prompts:
        parsed = self._structured_completion(_build_messages(scene), Prompts)
        image_prompt = parsed.image_prompt
        if scene.storyboard.required_elements:
            image_prompt = f"{image_prompt}, {', '.join(scene.storyboard.required_elements)}"
        return Prompts(
            image_prompt=image_prompt,
            video_motion_prompt=parsed.video_motion_prompt,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_prompt_agent.py -v`
Expected: PASS (14 passed — 13 pre-existing + 1 new schema-guard test)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (118 existing + 1 new = 119 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_prompt_agent.py tests/agents/test_openai_prompt_agent.py
git commit -m "refactor: migrate OpenAIPromptAgent onto BaseOpenAIAgent"
```

- [ ] **Step 7: Remove the temporary re-export in `openai_planning_agent.py`**

By this point, `openai_storyboard_agent.py` (Task 3) and `openai_prompt_agent.py` (this task, Step 3) both import `MissingAPIKeyError` directly from `openai_agent_base`, and both test files' import lines were already corrected in their own tasks. Nothing left in the codebase needs `openai_planning_agent.py` to re-export it. In `src/video_draft_pipeline/agents/openai_planning_agent.py`, change the top import line:

```python
from .openai_agent_base import BaseOpenAIAgent, MissingAPIKeyError
```

to:

```python
from .openai_agent_base import BaseOpenAIAgent
```

Run: `pytest -q`
Expected: all tests still pass (119 passed — this is a pure import cleanup, `MissingAPIKeyError` was never referenced by name anywhere else in `openai_planning_agent.py`'s own code, only imported for re-export purposes).

Commit:

```bash
git add src/video_draft_pipeline/agents/openai_planning_agent.py
git commit -m "refactor: remove temporary MissingAPIKeyError re-export from openai_planning_agent"
```

---

## Self-Review Notes

- **Spec coverage:** Goals (eliminate duplication, fix M1 empty-choices guard, fix M3 via schema guard, preserve all public behavior, keep exceptions distinct) → Tasks 1-4 collectively. Non-goals (no `run()` signature changes, no `_build_messages` extraction, no orchestrator wiring, no test-helper consolidation beyond the schema guard) → untouched, not in any task; verified the full-file replacements in Tasks 2-4 keep every agent-specific function (`_build_messages`, `_drafts_to_scenes`, the required-elements append) byte-identical to today. Architecture (`BaseOpenAIAgent`, `error_cls` class attribute, no re-export shim) → Task 1 (creation) and Tasks 2-4 (adoption + import fixes). Error handling (three failure modes uniformly wrapped) → Task 1. Testing (base class tests, schema guard + its self-test, one guard test per response-format type, no existing assertions changed) → all four tasks.
- **Placeholder scan:** no TBD/TODO markers; every step has complete, final code, including full-file replacements for all three migrated agents (chosen over incremental diffs specifically to avoid any ambiguity about what changes vs. stays the same).
- **Type consistency:** `error_cls: type[Exception]` in Task 1's `BaseOpenAIAgent` matches its use as a plain class attribute assignment (`error_cls = PlanningAgentError`, etc.) in Tasks 2-4 — no metaclass or abstract-property machinery needed since Python resolves `self.error_cls` via normal attribute lookup. `_structured_completion(messages, response_format) -> BaseModel` in Task 1 matches its call sites in Tasks 2-4 exactly (`self._structured_completion(_build_messages(...), ResponseFormatType)`). `assert_strict_schema_safe(model: type) -> None` in Task 1 matches its four call sites across Tasks 2-4. Confirmed the exact current import blocks of all three existing test files (read directly, not from memory) before writing each Task's Step 1, so the before/after import-fix instructions are byte-accurate.
