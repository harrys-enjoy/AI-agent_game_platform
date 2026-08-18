# OpenAIStoryboardAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a real `OpenAIStoryboardAgent` that turns a `Narrative` + `ProjectInput` into a `list[Scene]` via the OpenAI API, coexisting with (not replacing) the existing stub `StoryboardAgent`.

**Architecture:** One new file, `src/video_draft_pipeline/agents/openai_storyboard_agent.py`, exposing `.run(narrative, project_input) -> list[Scene]`, matching the stub's shape. The model only produces creative fields plus a relative `duration_weight` per beat, via a local throwaway response contract (`SceneDraft`/`StoryboardDraft`) that never leaves this file. Python deterministically converts that into real `Scene` objects: exact-duration math (weights scaled against `project_input.duration_sec`, remainder absorbed by the last scene), sequential `scene_id`/`order`, and a hard-coded rule forcing `required_elements` onto only the resolution scene from `project_input.brand_requirements` — never from the model's own output. Key resolution, client injection, and error wrapping follow the same pattern as `OpenAIPlanningAgent`, including reusing its `MissingAPIKeyError` by import rather than redefining it.

**Tech Stack:** Python 3.11+, Pydantic v2, `openai` Python SDK (already a runtime dependency), pytest + `unittest.mock`.

## Global Constraints

- The existing stub `src/video_draft_pipeline/agents/storyboard_agent.py` and its tests (`tests/agents/test_storyboard_agent.py`) are not modified.
- `MissingAPIKeyError` is imported from `video_draft_pipeline.agents.openai_planning_agent`, not redefined.
- `SceneDraft`/`StoryboardDraft` are defined in `openai_storyboard_agent.py` only — never added to `schema.py`, never imported elsewhere.
- No task may make a real network call or require a real API key. All tests run fully offline (mock the OpenAI SDK client boundary, or exercise pure functions directly with no client at all).
- `run_pipeline`/`orchestrator.py` wiring is out of scope (non-goal in the spec, `docs/superpowers/specs/2026-07-29-openai-storyboard-agent-design.md`).
- The existing 71 tests must continue to pass unchanged after every task.
- Generated creative text content (system/user prompts asking for Korean output) follows the project's Korean-language convention — the prompt must explicitly instruct the model to respond in Korean.

---

### Task 1: Exceptions, draft models, and fail-fast constructor

**Files:**
- Create: `src/video_draft_pipeline/agents/openai_storyboard_agent.py`
- Test: `tests/agents/test_openai_storyboard_agent.py`

**Interfaces:**
- Consumes: `video_draft_pipeline.config.load_api_keys() -> ApiKeys` (existing), `video_draft_pipeline.agents.openai_planning_agent.MissingAPIKeyError` (existing, imported not redefined), `video_draft_pipeline.schema.BeatId` (existing `Literal["setup", "conflict", "climax", "resolution"]`).
- Produces:
  - `class StoryboardAgentError(Exception)`
  - `class SceneDraft(BaseModel)`: `beat_id: BeatId`, `camera: str`, `subject: str`, `action: str`, `setting: str`, `required_elements: list[str]`, `duration_weight: float` (must be `> 0`)
  - `class StoryboardDraft(BaseModel)`: `scenes: list[SceneDraft]`
  - `class OpenAIStoryboardAgent.__init__(self, model_name: str = "gpt-5.4", api_key: str | None = None, client: "OpenAI | None" = None)` — raises `MissingAPIKeyError` if no key resolves; otherwise sets `self.model_name`, `self.api_key`, `self._client`.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_openai_storyboard_agent.py`:

```python
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from video_draft_pipeline.agents.openai_planning_agent import MissingAPIKeyError
from video_draft_pipeline.agents.openai_storyboard_agent import (
    OpenAIStoryboardAgent,
    SceneDraft,
)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        OpenAIStoryboardAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIStoryboardAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIStoryboardAgent(client=MagicMock())

    assert agent.api_key == "env-key"


def test_default_model_name_is_gpt_5_4(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIStoryboardAgent(client=MagicMock())

    assert agent.model_name == "gpt-5.4"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIStoryboardAgent(model_name="custom-storyboarder", client=MagicMock())

    assert agent.model_name == "custom-storyboarder"


def test_scene_draft_rejects_non_positive_weight():
    with pytest.raises(ValidationError):
        SceneDraft(
            beat_id="setup",
            camera="와이드 샷",
            subject="주인공",
            action="등장",
            setting="필드",
            required_elements=[],
            duration_weight=0,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.openai_storyboard_agent'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/video_draft_pipeline/agents/openai_storyboard_agent.py`:

```python
from openai import OpenAI
from pydantic import BaseModel, Field

from .. import config
from ..schema import BeatId
from .openai_planning_agent import MissingAPIKeyError


class StoryboardAgentError(Exception):
    pass


class SceneDraft(BaseModel):
    beat_id: BeatId
    camera: str
    subject: str
    action: str
    setting: str
    required_elements: list[str]
    duration_weight: float = Field(gt=0)


class StoryboardDraft(BaseModel):
    scenes: list[SceneDraft]


class OpenAIStoryboardAgent:
    def __init__(
        self,
        model_name: str = "gpt-5.4",
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

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (71 existing + 6 new = 77 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_storyboard_agent.py tests/agents/test_openai_storyboard_agent.py
git commit -m "feat: add OpenAIStoryboardAgent with draft models and fail-fast key resolution"
```

---

### Task 2: Prompt/message builder

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_storyboard_agent.py`
- Test: `tests/agents/test_openai_storyboard_agent.py`

**Interfaces:**
- Consumes: `video_draft_pipeline.schema.Narrative` (`.beats: list[Beat]`, each with `.beat_id`, `.description`, `.tone`), `video_draft_pipeline.schema.ProjectInput` (`.preset`, `.scene_type`, `.brief`) — all existing.
- Produces: module-level function `_build_messages(narrative: Narrative, project_input: ProjectInput) -> list[dict]` returning `[{"role": "system", "content": str}, {"role": "user", "content": str}]`, consumed by Task 4's `run()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_storyboard_agent.py`:

```python
from video_draft_pipeline.agents.openai_storyboard_agent import _build_messages
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput


def test_build_messages_has_system_then_user_role():
    narrative = Narrative(
        beats=[Beat(beat_id="setup", description="시작", tone="calm")]
    )
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=15, brief="신규 캐릭터 공개"
    )

    messages = _build_messages(narrative, project_input)

    assert [m["role"] for m in messages] == ["system", "user"]


def test_build_messages_includes_beat_details():
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="평화로운 상황", tone="calm"),
            Beat(beat_id="climax", description="절정", tone="epic"),
        ]
    )
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=15, brief="신규 캐릭터 공개"
    )

    messages = _build_messages(narrative, project_input)
    user_content = messages[1]["content"]

    assert "평화로운 상황" in user_content
    assert "절정" in user_content
    assert "setup" in user_content
    assert "climax" in user_content


def test_build_messages_includes_project_input_fields():
    narrative = Narrative(
        beats=[Beat(beat_id="setup", description="시작", tone="calm")]
    )
    project_input = ProjectInput(
        preset="이벤트", scene_type="스튜디오", duration_sec=20, brief="할로윈 이벤트"
    )

    messages = _build_messages(narrative, project_input)
    user_content = messages[1]["content"]

    assert "이벤트" in user_content
    assert "스튜디오" in user_content
    assert "할로윈 이벤트" in user_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v -k build_messages`
Expected: FAIL with `ImportError: cannot import name '_build_messages'`

- [ ] **Step 3: Write the minimal implementation**

In `src/video_draft_pipeline/agents/openai_storyboard_agent.py`, change the top import line:

```python
from ..schema import BeatId
```

to:

```python
from ..schema import BeatId, Narrative, ProjectInput
```

Then add this function (below the imports, above `StoryboardAgentError`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (71 existing + 9 new = 80 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_storyboard_agent.py tests/agents/test_openai_storyboard_agent.py
git commit -m "feat: add OpenAIStoryboardAgent prompt/message builder"
```

---

### Task 3: Deterministic draft-to-scene conversion

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_storyboard_agent.py`
- Test: `tests/agents/test_openai_storyboard_agent.py`

**Interfaces:**
- Consumes: `SceneDraft` (Task 1), `video_draft_pipeline.schema.ProjectInput` (`.duration_sec`, `.brand_requirements`), `video_draft_pipeline.schema.Scene`, `video_draft_pipeline.schema.Storyboard` (existing).
- Produces: module-level function `_drafts_to_scenes(drafts: list[SceneDraft], project_input: ProjectInput) -> list[Scene]`, consumed by Task 4's `run()`. This function takes no OpenAI client and makes no network call — it is pure and directly testable.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_storyboard_agent.py`:

```python
from video_draft_pipeline.agents.openai_storyboard_agent import _drafts_to_scenes
from video_draft_pipeline.schema import Scene


def _draft(beat_id, weight, required_elements=None):
    return SceneDraft(
        beat_id=beat_id,
        camera="와이드 샷",
        subject="주인공",
        action="등장",
        setting="필드",
        required_elements=required_elements or [],
        duration_weight=weight,
    )


def test_drafts_to_scenes_computes_exact_duration_sum_even_division():
    drafts = [
        _draft("setup", 1),
        _draft("conflict", 1),
        _draft("climax", 2),
        _draft("resolution", 1),
    ]
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=30, brief="브리프"
    )

    scenes = _drafts_to_scenes(drafts, project_input)

    assert sum(scene.duration_sec for scene in scenes) == 30
    assert scenes[2].duration_sec == 12.0
    assert scenes[0].duration_sec == 6.0


def test_drafts_to_scenes_computes_exact_duration_sum_uneven_division():
    drafts = [_draft("setup", 1), _draft("conflict", 1), _draft("resolution", 1)]
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=10, brief="브리프"
    )

    scenes = _drafts_to_scenes(drafts, project_input)

    assert abs(sum(scene.duration_sec for scene in scenes) - 10) < 1e-9
    assert all(scene.duration_sec > 0 for scene in scenes)


def test_drafts_to_scenes_sets_scene_id_and_order_sequentially():
    drafts = [_draft("setup", 1), _draft("resolution", 1)]
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=10, brief="브리프"
    )

    scenes = _drafts_to_scenes(drafts, project_input)

    assert [s.scene_id for s in scenes] == ["scene_01", "scene_02"]
    assert [s.order for s in scenes] == [1, 2]
    assert isinstance(scenes[0], Scene)


def test_drafts_to_scenes_forces_required_elements_only_on_resolution():
    drafts = [
        _draft("setup", 1, required_elements=["모델이 제안한 요소"]),
        _draft("resolution", 1, required_elements=[]),
    ]
    project_input = ProjectInput(
        preset="공개",
        scene_type="인게임",
        duration_sec=10,
        brief="브리프",
        brand_requirements=["로고 노출"],
    )

    scenes = _drafts_to_scenes(drafts, project_input)

    assert scenes[0].storyboard.required_elements == []
    assert scenes[1].storyboard.required_elements == ["로고 노출"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v -k drafts_to_scenes`
Expected: FAIL with `ImportError: cannot import name '_drafts_to_scenes'`

- [ ] **Step 3: Write the minimal implementation**

In `src/video_draft_pipeline/agents/openai_storyboard_agent.py`, change the top import line:

```python
from ..schema import BeatId, Narrative, ProjectInput
```

to:

```python
from ..schema import BeatId, Narrative, ProjectInput, Scene, Storyboard
```

Then add this function (below `_build_messages`, above `StoryboardAgentError`):

```python
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
```

(Note: `SceneDraft` is defined earlier in this same file, above this function — no new import needed for it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (71 existing + 13 new = 84 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_storyboard_agent.py tests/agents/test_openai_storyboard_agent.py
git commit -m "feat: add deterministic draft-to-scene conversion for OpenAIStoryboardAgent"
```

---

### Task 4: `run()` — Structured Outputs call, validation, and conversion

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_storyboard_agent.py`
- Test: `tests/agents/test_openai_storyboard_agent.py`

**Interfaces:**
- Consumes: `_build_messages` (Task 2), `_drafts_to_scenes` (Task 3), `self.model_name`, `self._client` (Task 1), `StoryboardDraft` (Task 1), `video_draft_pipeline.schema.Narrative`.
- Produces: `OpenAIStoryboardAgent.run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]`. Raises `StoryboardAgentError` if the SDK call fails, the model refuses, or the response's beats don't match the narrative's beats (wrong count and/or wrong order).

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_storyboard_agent.py`:

```python
from types import SimpleNamespace

from video_draft_pipeline.agents.openai_storyboard_agent import StoryboardAgentError


def _fake_completion(parsed=None, refusal=None) -> SimpleNamespace:
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _narrative_four_beats():
    return Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )


def test_run_returns_scenes_from_valid_draft(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[
            _draft("setup", 1),
            _draft("conflict", 1),
            _draft("climax", 2),
            _draft("resolution", 1),
        ]
    )
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(parsed=draft)
    agent = OpenAIStoryboardAgent(client=client)
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=30, brief="브리프"
    )

    scenes = agent.run(narrative, project_input)

    assert [s.beat_id for s in scenes] == ["setup", "conflict", "climax", "resolution"]
    assert sum(s.duration_sec for s in scenes) == 30


def test_run_calls_sdk_with_expected_model_and_response_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[
            _draft("setup", 1),
            _draft("conflict", 1),
            _draft("climax", 1),
            _draft("resolution", 1),
        ]
    )
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(parsed=draft)
    agent = OpenAIStoryboardAgent(model_name="custom-storyboarder", client=client)
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=30, brief="브리프"
    )

    agent.run(narrative, project_input)

    _, kwargs = client.chat.completions.parse.call_args
    assert kwargs["model"] == "custom-storyboarder"
    assert kwargs["response_format"] is StoryboardDraft
    assert kwargs["messages"] == _build_messages(narrative, project_input)


def test_run_raises_on_beat_mismatch(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 1)]
    )
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(parsed=draft)
    agent = OpenAIStoryboardAgent(client=client)
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=30, brief="브리프"
    )

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)


def test_run_raises_on_refusal(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_completion(
        parsed=None, refusal="cannot help with that"
    )
    agent = OpenAIStoryboardAgent(client=client)
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=30, brief="브리프"
    )

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    client = MagicMock()
    client.chat.completions.parse.side_effect = RuntimeError("boom")
    agent = OpenAIStoryboardAgent(client=client)
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=30, brief="브리프"
    )

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)
```

(The `_fake_completion` helper above differs from Task 1-3's `_draft` helper only in name — both live in the same test file; do not duplicate `_draft`, it was already added in Task 3.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v -k test_run_`
Expected: FAIL with `AttributeError: 'OpenAIStoryboardAgent' object has no attribute 'run'`

- [ ] **Step 3: Write the minimal implementation**

In `src/video_draft_pipeline/agents/openai_storyboard_agent.py`, add a `run` method to `OpenAIStoryboardAgent` (after `__init__`):

```python
    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]:
        try:
            completion = self._client.chat.completions.parse(
                model=self.model_name,
                messages=_build_messages(narrative, project_input),
                response_format=StoryboardDraft,
            )
        except Exception as exc:
            raise StoryboardAgentError(f"OpenAI storyboard call failed: {exc}") from exc
        message = completion.choices[0].message
        if message.parsed is None:
            raise StoryboardAgentError(
                f"OpenAI storyboard call returned no storyboard: {message.refusal or 'empty response'}"
            )
        draft_beat_ids = [scene.beat_id for scene in message.parsed.scenes]
        expected_beat_ids = [beat.beat_id for beat in narrative.beats]
        if draft_beat_ids != expected_beat_ids:
            raise StoryboardAgentError(
                f"OpenAI storyboard response beats {draft_beat_ids} do not match "
                f"narrative beats {expected_beat_ids}"
            )
        return _drafts_to_scenes(message.parsed.scenes, project_input)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_storyboard_agent.py -v`
Expected: PASS (18 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (71 existing + 18 new = 89 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_storyboard_agent.py tests/agents/test_openai_storyboard_agent.py
git commit -m "feat: implement OpenAIStoryboardAgent.run with beat-alignment validation"
```

---

## Self-Review Notes

- **Spec coverage:** Goals (real agent producing `list[Scene]`, dynamic weighted pacing, deterministic structural fields, fail-loud validation, stub untouched) → Tasks 1, 3, 4. Non-goals (no orchestrator wiring, no live test, no other agents, no shared-plumbing extraction) → untouched, not in any task. Architecture (new file, draft models local, `MissingAPIKeyError` reused not redefined) → Task 1. Key resolution → Task 1. Draft shape and validation (refusal check, alignment check, `duration_weight > 0`) → Tasks 1 and 4. Deterministic conversion (duration math, scene_id/order, forced required_elements) → Task 3. Error handling (one exception type) → Task 4. Testing (key-free, including the direct `SceneDraft` validation test and the pure `_drafts_to_scenes` tests) → Tasks 1, 3, 4.
- **Placeholder scan:** no TBD/TODO markers; every step has full, final code with no scaffolding to discard.
- **Type consistency:** `SceneDraft`/`StoryboardDraft` signatures in Task 1 match their construction in Tasks 3-4's tests and `run()`'s usage. `_build_messages(narrative, project_input)` signature in Task 2 matches its call in Task 4. `_drafts_to_scenes(drafts, project_input)` signature in Task 3 matches its call in Task 4. `StoryboardAgentError` name matches between Task 1's definition and Task 4's raises. `MissingAPIKeyError` import path (`video_draft_pipeline.agents.openai_planning_agent`) matches the actual location established in the prior plan.
