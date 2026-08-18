# Gemini Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working, direct-Gemini alternative to the pipeline's 5 Elice-proxied agents (planning, storyboard, prompt, image, director) on an isolated branch, so `master` stays on today's Elice-backed default until a deliberate merge decision.

**Architecture:** Five new agent classes (`GeminiPlanningAgent`, `GeminiStoryboardAgent`, `GeminiPromptAgent`, `GeminiImageAgent`, `GeminiDirectorAgent`), each a drop-in replacement conforming to the exact `Protocol` its Elice-backed sibling already implements. `GeminiReviewAgent`/`GeminiImageEditAgent` get their model defaults corrected. `build_real_agents()`, `ModelConfig`/`ApiKeys`, and docs are updated for an all-Gemini setup. Zero changes to `orchestrator.py`, `protocols.py`, or any schema — every new class satisfies an existing `Protocol`.

**Tech Stack:** Python, `google-genai` SDK (already a dependency), `pydantic`, `pytest`.

## Global Constraints

- All Gemini model ID strings in this plan are bare — no `google/` prefix (that prefix was Elice's proxy-routing convention; direct Google AI Studio calls use the raw model ID).
- No `temperature` override anywhere — Google's own docs recommend leaving Gemini 3 models at their default (1.0).
- No `thinking_level`/`generation_config` override anywhere — not confirmed supported for the specific models used here; left at model defaults.
- No new dependencies — `google-genai` already covers every agent in this plan.
- `GeminiDirectorAgent` must preserve `NemotronDirectorAgent`'s exact safety invariant: the LLM is always called, but `decision` is deterministically forced to `"reject"` once `scene.retry_count >= scene.max_retries`, regardless of what the model returns.
- New agents do not set `base_url_config_field` (inherits `BaseGeminiAgent`'s default of `None`) — there is no Elice gateway to point at.
- Spec: `docs/superpowers/specs/2026-08-03-gemini-unification-design.md`.

## Branch Setup (do this before Task 1, not as part of any task)

This plan's work happens on an isolated branch, not `master` (explicit user decision — this project's usual convention is straight-to-master, but this exploration is deliberately isolated so `master` is unaffected until a real merge decision). Before dispatching Task 1:

```bash
git checkout -b gemini-unification
```

All tasks below assume this branch is already checked out. Every task's commit lands on `gemini-unification`, not `master`.

---

### Task 1: `GeminiPlanningAgent`

**Files:**
- Create: `src/video_draft_pipeline/agents/gemini_planning_agent.py`
- Test: `tests/agents/test_gemini_planning_agent.py`

**Interfaces:**
- Consumes: `BaseGeminiAgent.__init__(model_name, api_key, client, base_url)` and `BaseGeminiAgent._structured_interaction(input_content: list[dict], response_schema: type[BaseModel]) -> BaseModel` (`src/video_draft_pipeline/agents/gemini_agent_base.py`); `schema.Narrative`, `schema.ProjectInput`.
- Produces: `GeminiPlanningAgent(model_name="gemini-3.1-pro-preview", api_key=None, client=None, base_url=None)` with `.run(project_input: ProjectInput) -> Narrative` and `.estimate_cost() -> float`; `PlanningAgentError`; module-level `_build_input(project_input: ProjectInput) -> str`. Task 8 (factory) constructs this class by name.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_gemini_planning_agent.py
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_planning_agent import (
    GeminiPlanningAgent,
    PlanningAgentError,
    _build_input,
)
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiPlanningAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(client=MagicMock())

    assert agent.api_key == "env-key"


def test_default_model_name_is_gemini_3_1_pro_preview(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.1-pro-preview"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(model_name="custom-planner", client=MagicMock())

    assert agent.model_name == "custom-planner"


def test_build_input_includes_fields():
    project_input = ProjectInput(
        preset="공개",
        scene_type="인게임",
        duration_sec=15,
        brief="신규 캐릭터 공개",
        brand_requirements=["로고 노출"],
    )

    text = _build_input(project_input)

    assert "신규 캐릭터 공개" in text
    assert "공개" in text
    assert "인게임" in text
    assert "로고 노출" in text


def test_build_input_handles_empty_brand_requirements():
    project_input = ProjectInput(
        preset="이벤트", scene_type="스튜디오", duration_sec=10, brief="브리프"
    )

    text = _build_input(project_input)

    assert text


def _narrative():
    return Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )


def _fake_interaction(output_text: str):
    from types import SimpleNamespace

    return SimpleNamespace(output_text=output_text)


def test_run_returns_parsed_narrative(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative()
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(narrative.model_dump_json())
    agent = GeminiPlanningAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    result = agent.run(project_input)

    assert result == narrative


def test_run_calls_sdk_with_expected_model_and_input(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative()
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(narrative.model_dump_json())
    agent = GeminiPlanningAgent(model_name="custom-planner", client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    agent.run(project_input)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "custom-planner"
    input_content = kwargs["input"]
    assert input_content[0]["type"] == "text"
    assert input_content[0]["text"] == _build_input(project_input)


def test_run_wraps_sdk_exception_as_planning_agent_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiPlanningAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    with pytest.raises(PlanningAgentError):
        agent.run(project_input)


def test_run_wraps_malformed_json_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = GeminiPlanningAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=15, brief="브리프")

    with pytest.raises(PlanningAgentError):
        agent.run(project_input)


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPlanningAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.01
    assert agent.estimate_cost() == GeminiPlanningAgent.ESTIMATED_COST_USD
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_gemini_planning_agent.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'video_draft_pipeline.agents.gemini_planning_agent'`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_draft_pipeline/agents/gemini_planning_agent.py
from ..schema import Narrative, ProjectInput
from .gemini_agent_base import BaseGeminiAgent


def _build_input(project_input: ProjectInput) -> str:
    requirements = ", ".join(project_input.brand_requirements) or "none"
    return (
        "You are a creative director generating a 4-beat narrative for a game "
        "marketing video draft. Produce exactly one beat for each of: "
        "setup, conflict, climax, resolution.\n\n"
        f"Preset: {project_input.preset}\n"
        f"Scene type: {project_input.scene_type}\n"
        f"Brief: {project_input.brief}\n"
        f"Brand requirements: {requirements}"
    )


class PlanningAgentError(Exception):
    pass


class GeminiPlanningAgent(BaseGeminiAgent):
    error_cls = PlanningAgentError
    ESTIMATED_COST_USD = 0.01

    def __init__(
        self,
        model_name: str = "gemini-3.1-pro-preview",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, project_input: ProjectInput) -> Narrative:
        input_content = [{"type": "text", "text": _build_input(project_input)}]
        return self._structured_interaction(input_content, Narrative)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_gemini_planning_agent.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/gemini_planning_agent.py tests/agents/test_gemini_planning_agent.py
git commit -m "feat: add GeminiPlanningAgent"
```

---

### Task 2: `GeminiStoryboardAgent`

**Files:**
- Create: `src/video_draft_pipeline/agents/gemini_storyboard_agent.py`
- Test: `tests/agents/test_gemini_storyboard_agent.py`

**Interfaces:**
- Consumes: `BaseGeminiAgent` (same as Task 1); `schema.BeatId`, `schema.Narrative`, `schema.ProjectInput`, `schema.Scene`, `schema.Storyboard`.
- Produces: `GeminiStoryboardAgent(model_name="gemini-3.6-flash", api_key=None, client=None, base_url=None)` with `.run(narrative: Narrative, project_input: ProjectInput) -> list[Scene]` and `.estimate_cost() -> float`; `StoryboardAgentError`; `SceneDraft`, `StoryboardDraft` (pydantic models); module-level `_build_input`, `_drafts_to_scenes`. Independent of Task 1 — no shared code.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_gemini_storyboard_agent.py
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_storyboard_agent import (
    GeminiStoryboardAgent,
    SceneDraft,
    StoryboardAgentError,
    StoryboardDraft,
    _build_input,
    _drafts_to_scenes,
)
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput, Scene


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiStoryboardAgent()


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiStoryboardAgent(api_key="explicit-key", client=MagicMock())

    assert agent.api_key == "explicit-key"


def test_default_model_name_is_gemini_3_6_flash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiStoryboardAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.6-flash"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiStoryboardAgent(model_name="custom-storyboarder", client=MagicMock())

    assert agent.model_name == "custom-storyboarder"


def test_scene_draft_allows_non_positive_weight_at_construction():
    draft = SceneDraft(
        beat_id="setup", camera="와이드 샷", subject="주인공", action="등장",
        setting="필드", required_elements=[], duration_weight=0,
    )

    assert draft.duration_weight == 0


def test_build_input_includes_beat_and_project_details():
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="평화로운 상황", tone="calm"),
            Beat(beat_id="climax", description="절정", tone="epic"),
        ]
    )
    project_input = ProjectInput(
        preset="이벤트", scene_type="스튜디오", duration_sec=20, brief="할로윈 이벤트"
    )

    text = _build_input(narrative, project_input)

    assert "평화로운 상황" in text
    assert "절정" in text
    assert "setup" in text
    assert "climax" in text
    assert "이벤트" in text
    assert "스튜디오" in text
    assert "할로윈 이벤트" in text


def _draft(beat_id, weight, required_elements=None):
    return SceneDraft(
        beat_id=beat_id, camera="와이드 샷", subject="주인공", action="등장",
        setting="필드", required_elements=required_elements or [], duration_weight=weight,
    )


def test_drafts_to_scenes_computes_exact_duration_sum_even_division():
    drafts = [_draft("setup", 1), _draft("conflict", 1), _draft("climax", 2), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input)

    assert sum(scene.duration_sec for scene in scenes) == 30
    assert scenes[2].duration_sec == 12.0


def test_drafts_to_scenes_sets_scene_id_and_order_sequentially():
    drafts = [_draft("setup", 1), _draft("resolution", 1)]
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=10, brief="브리프")

    scenes = _drafts_to_scenes(drafts, project_input)

    assert [s.scene_id for s in scenes] == ["scene_01", "scene_02"]
    assert isinstance(scenes[0], Scene)


def test_drafts_to_scenes_forces_required_elements_only_on_resolution():
    drafts = [
        _draft("setup", 1, required_elements=["모델이 제안한 요소"]),
        _draft("resolution", 1, required_elements=[]),
    ]
    project_input = ProjectInput(
        preset="공개", scene_type="인게임", duration_sec=10, brief="브리프",
        brand_requirements=["로고 노출"],
    )

    scenes = _drafts_to_scenes(drafts, project_input)

    assert scenes[0].storyboard.required_elements == []
    assert scenes[1].storyboard.required_elements == ["로고 노출"]


def _narrative_four_beats():
    return Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )


def _fake_interaction(output_text: str):
    return SimpleNamespace(output_text=output_text)


def test_run_returns_scenes_from_valid_draft(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 2), _draft("resolution", 1)]
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    scenes = agent.run(narrative, project_input)

    assert [s.beat_id for s in scenes] == ["setup", "conflict", "climax", "resolution"]
    assert sum(s.duration_sec for s in scenes) == 30


def test_run_calls_sdk_with_expected_model_and_input(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 1), _draft("resolution", 1)]
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(model_name="custom-storyboarder", client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    agent.run(narrative, project_input)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "custom-storyboarder"
    assert kwargs["input"][0]["text"] == _build_input(narrative, project_input)


def test_run_raises_on_beat_mismatch(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 1)])
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)


def test_run_raises_on_non_positive_duration_weight(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    draft = StoryboardDraft(
        scenes=[_draft("setup", 1), _draft("conflict", 1), _draft("climax", 0), _draft("resolution", 1)]
    )
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(draft.model_dump_json())
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)


def test_run_raises_on_empty_beats(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = Narrative(beats=[])
    client = MagicMock()
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)

    client.interactions.create.assert_not_called()


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    narrative = _narrative_four_beats()
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiStoryboardAgent(client=client)
    project_input = ProjectInput(preset="공개", scene_type="인게임", duration_sec=30, brief="브리프")

    with pytest.raises(StoryboardAgentError):
        agent.run(narrative, project_input)


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiStoryboardAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.01
    assert agent.estimate_cost() == GeminiStoryboardAgent.ESTIMATED_COST_USD
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_gemini_storyboard_agent.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_draft_pipeline/agents/gemini_storyboard_agent.py
from pydantic import BaseModel, ValidationError

from ..schema import BeatId, Narrative, ProjectInput, Scene, Storyboard
from .gemini_agent_base import BaseGeminiAgent


def _build_input(narrative: Narrative, project_input: ProjectInput) -> str:
    beats_description = "\n".join(
        f"- {beat.beat_id}: {beat.description} (tone: {beat.tone})" for beat in narrative.beats
    )
    return (
        "You are a creative director generating a shot-by-shot storyboard for a "
        "game marketing video draft. For each beat provided, produce one scene: "
        "a camera direction, the subject, the action, the setting, any required "
        "on-screen elements, and a duration_weight expressing how much relative "
        "screen time this beat deserves compared to the others (for example, a "
        "climax beat might deserve more weight than a setup beat). Respond in "
        "Korean, matching the language of the input.\n\n"
        f"Preset: {project_input.preset}\n"
        f"Scene type: {project_input.scene_type}\n"
        f"Brief: {project_input.brief}\n"
        f"Beats:\n{beats_description}"
    )


def _drafts_to_scenes(drafts: list["SceneDraft"], project_input: ProjectInput) -> list[Scene]:
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
            list(project_input.brand_requirements) if draft.beat_id == "resolution" else []
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


class GeminiStoryboardAgent(BaseGeminiAgent):
    error_cls = StoryboardAgentError
    ESTIMATED_COST_USD = 0.01

    def __init__(
        self,
        model_name: str = "gemini-3.6-flash",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]:
        if not narrative.beats:
            raise StoryboardAgentError("Narrative has no beats; cannot build a storyboard.")
        input_content = [{"type": "text", "text": _build_input(narrative, project_input)}]
        draft = self._structured_interaction(input_content, StoryboardDraft)
        draft_beat_ids = [scene.beat_id for scene in draft.scenes]
        expected_beat_ids = [beat.beat_id for beat in narrative.beats]
        if draft_beat_ids != expected_beat_ids:
            raise StoryboardAgentError(
                f"Gemini storyboard response beats {draft_beat_ids} do not match "
                f"narrative beats {expected_beat_ids}"
            )
        if any(scene.duration_weight <= 0 for scene in draft.scenes):
            raise StoryboardAgentError(
                "Gemini storyboard response contained a non-positive duration_weight"
            )
        try:
            return _drafts_to_scenes(draft.scenes, project_input)
        except ValidationError as exc:
            raise StoryboardAgentError(f"Gemini storyboard produced unusable durations: {exc}") from exc

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_gemini_storyboard_agent.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/gemini_storyboard_agent.py tests/agents/test_gemini_storyboard_agent.py
git commit -m "feat: add GeminiStoryboardAgent"
```

---

### Task 3: `GeminiPromptAgent`

**Files:**
- Create: `src/video_draft_pipeline/agents/gemini_prompt_agent.py`
- Test: `tests/agents/test_gemini_prompt_agent.py`

**Interfaces:**
- Consumes: `BaseGeminiAgent` (Task 1); `schema.Prompts`, `schema.Scene`.
- Produces: `GeminiPromptAgent(model_name="gemini-3.5-flash-lite", api_key=None, client=None, base_url=None)` with `.run(scene: Scene, feedback: str | None = None) -> Prompts` and `.estimate_cost() -> float`; `PromptAgentError`. Independent of Tasks 1–2.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_gemini_prompt_agent.py
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_prompt_agent import (
    GeminiPromptAgent,
    PromptAgentError,
    _build_input,
)
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.schema import Prompts, Scene, Storyboard


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiPromptAgent()


def test_default_model_name_is_gemini_3_5_flash_lite(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPromptAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.5-flash-lite"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPromptAgent(model_name="custom-prompter", client=MagicMock())

    assert agent.model_name == "custom-prompter"


def _scene(required_elements=None):
    return Scene(
        scene_id="scene_01", beat_id="conflict", order=1, duration_sec=6,
        storyboard=Storyboard(
            camera="슬로우 팬, 성벽 따라 이동", subject="호박 몬스터 무리",
            action="성벽을 타고 올라옴", setting="성 외곽, 야간",
            required_elements=required_elements or [],
        ),
    )


def test_build_input_includes_storyboard_fields():
    text = _build_input(_scene())

    assert "슬로우 팬, 성벽 따라 이동" in text
    assert "호박 몬스터 무리" in text


def test_build_input_includes_feedback_when_present():
    text = _build_input(_scene(), feedback="fix the lighting")

    assert "fix the lighting" in text


def test_build_input_omits_feedback_section_when_none():
    text = _build_input(_scene(), feedback=None)

    assert "director" not in text.lower()


def _fake_interaction(output_text: str):
    return SimpleNamespace(output_text=output_text)


def test_run_appends_required_elements_when_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene(required_elements=["이벤트 로고 노출"])
    parsed = Prompts(image_prompt="야간 성벽, 몬스터 무리", video_motion_prompt="슬로우 팬")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(parsed.model_dump_json())
    agent = GeminiPromptAgent(client=client)

    result = agent.run(scene)

    assert result.image_prompt == "야간 성벽, 몬스터 무리, 이벤트 로고 노출"


def test_run_leaves_image_prompt_unmodified_when_no_required_elements(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene(required_elements=[])
    parsed = Prompts(image_prompt="야간 성벽, 몬스터 무리", video_motion_prompt="슬로우 팬")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(parsed.model_dump_json())
    agent = GeminiPromptAgent(client=client)

    result = agent.run(scene)

    assert result.image_prompt == "야간 성벽, 몬스터 무리"


def test_run_passes_feedback_into_built_input(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene()
    parsed = Prompts(image_prompt="p", video_motion_prompt="m")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(parsed.model_dump_json())
    agent = GeminiPromptAgent(client=client)

    agent.run(scene, feedback="fix the lighting")

    _, kwargs = client.interactions.create.call_args
    assert kwargs["input"][0]["text"] == _build_input(scene, feedback="fix the lighting")


def test_run_calls_sdk_with_expected_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene()
    parsed = Prompts(image_prompt="p", video_motion_prompt="m")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(parsed.model_dump_json())
    agent = GeminiPromptAgent(model_name="custom-prompter", client=client)

    agent.run(scene)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "custom-prompter"


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene()
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiPromptAgent(client=client)

    with pytest.raises(PromptAgentError):
        agent.run(scene)


def test_run_wraps_malformed_json_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene()
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = GeminiPromptAgent(client=client)

    with pytest.raises(PromptAgentError):
        agent.run(scene)


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPromptAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.005
    assert agent.estimate_cost() == GeminiPromptAgent.ESTIMATED_COST_USD
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_gemini_prompt_agent.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_draft_pipeline/agents/gemini_prompt_agent.py
from ..schema import Prompts, Scene
from .gemini_agent_base import BaseGeminiAgent


def _build_input(scene: Scene, feedback: str | None = None) -> str:
    sb = scene.storyboard
    text = (
        "You are a prompt engineer generating an image generation prompt and a "
        "video motion prompt for a single scene of a game marketing video. "
        "image_prompt should describe the visual content: setting, subject, "
        "action, and camera framing. video_motion_prompt should describe only "
        "the camera movement and action, not static visual details. Respond "
        "in Korean, matching the language of the input.\n\n"
        f"Camera: {sb.camera}\n"
        f"Subject: {sb.subject}\n"
        f"Action: {sb.action}\n"
        f"Setting: {sb.setting}"
    )
    if feedback:
        text += (
            f"\n\nThe previous attempt was rejected with this feedback from the "
            f"director — revise the prompts to address it: {feedback}"
        )
    return text


class PromptAgentError(Exception):
    pass


class GeminiPromptAgent(BaseGeminiAgent):
    error_cls = PromptAgentError
    ESTIMATED_COST_USD = 0.005

    def __init__(
        self,
        model_name: str = "gemini-3.5-flash-lite",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, scene: Scene, feedback: str | None = None) -> Prompts:
        input_content = [{"type": "text", "text": _build_input(scene, feedback)}]
        parsed = self._structured_interaction(input_content, Prompts)
        image_prompt = parsed.image_prompt
        if scene.storyboard.required_elements:
            image_prompt = f"{image_prompt}, {', '.join(scene.storyboard.required_elements)}"
        return Prompts(image_prompt=image_prompt, video_motion_prompt=parsed.video_motion_prompt)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_gemini_prompt_agent.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/gemini_prompt_agent.py tests/agents/test_gemini_prompt_agent.py
git commit -m "feat: add GeminiPromptAgent"
```

---

### Task 4: `GeminiImageAgent`

**Files:**
- Create: `src/video_draft_pipeline/agents/gemini_image_agent.py`
- Test: `tests/agents/test_gemini_image_agent.py`

**Interfaces:**
- Consumes: `BaseGeminiAgent` (Task 1); `schema.Candidate`, `schema.Prompts`.
- Produces: `GeminiImageAgent(model_name="gemini-3.1-flash-image", output_dir="media", api_key=None, client=None, base_url=None)` with `.run(prompts: Prompts) -> Candidate` and `.estimate_cost() -> float`; `ImageAgentError`. Independent of Tasks 1–3.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_gemini_image_agent.py
import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_image_agent import GeminiImageAgent, ImageAgentError
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.schema import Prompts


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiImageAgent(output_dir=tmp_path / "media")


def test_default_model_name_is_gemini_3_1_flash_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "gemini-3.1-flash-image"


def test_custom_model_name_stored(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageAgent(model_name="custom-imager", client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "custom-imager"


def test_estimate_cost_returns_fixed_constant(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.estimate_cost() == 0.039
    assert agent.estimate_cost() == GeminiImageAgent.ESTIMATED_COST_USD


def _fake_interaction(output_image_b64: str) -> SimpleNamespace:
    return SimpleNamespace(output_image=SimpleNamespace(data=output_image_b64))


def test_run_calls_sdk_with_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(image_b64)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    agent.run(prompts)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "gemini-3.1-flash-image"
    assert kwargs["input"][0]["type"] == "text"
    assert kwargs["input"][0]["text"] == "a haunted castle"


def test_run_writes_image_and_returns_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    image_b64 = base64.b64encode(b"generated-image-bytes").decode("utf-8")
    client.interactions.create.return_value = _fake_interaction(image_b64)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    result = agent.run(prompts)

    assert result.generated_by == "gemini-3.1-flash-image"
    assert Path(result.image_url).exists()
    assert Path(result.image_url).read_bytes() == b"generated-image-bytes"


def test_run_wraps_sdk_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageAgentError):
        agent.run(prompts)


def test_run_wraps_missing_output_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(output_image=None)
    agent = GeminiImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    with pytest.raises(ImageAgentError):
        agent.run(prompts)


def test_output_dir_created_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    nested = tmp_path / "nested" / "media"

    GeminiImageAgent(client=MagicMock(), output_dir=nested)

    assert nested.is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_gemini_image_agent.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_draft_pipeline/agents/gemini_image_agent.py
import base64
import uuid
from pathlib import Path

from ..schema import Candidate, Prompts
from .gemini_agent_base import BaseGeminiAgent


class ImageAgentError(Exception):
    pass


class GeminiImageAgent(BaseGeminiAgent):
    error_cls = ImageAgentError
    ESTIMATED_COST_USD = 0.039

    def __init__(
        self,
        model_name: str = "gemini-3.1-flash-image",
        output_dir: str | Path = "media",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, prompts: Prompts) -> Candidate:
        input_content = [{"type": "text", "text": prompts.image_prompt}]
        try:
            interaction = self._client.interactions.create(model=self.model_name, input=input_content)
        except Exception as exc:
            raise self.error_cls(f"Gemini image call failed: {exc}") from exc
        if interaction.output_image is None:
            raise self.error_cls("Gemini image call returned no output image")

        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        image_bytes = base64.b64decode(interaction.output_image.data)
        file_path = self.output_dir / f"{candidate_id}.png"
        file_path.write_bytes(image_bytes)

        return Candidate(candidate_id=candidate_id, image_url=str(file_path), generated_by=self.model_name)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_gemini_image_agent.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/gemini_image_agent.py tests/agents/test_gemini_image_agent.py
git commit -m "feat: add GeminiImageAgent"
```

---

### Task 5: `GeminiDirectorAgent`

**Files:**
- Create: `src/video_draft_pipeline/agents/gemini_director_agent.py`
- Test: `tests/agents/test_gemini_director_agent.py`

**Interfaces:**
- Consumes: `BaseGeminiAgent` (Task 1); `schema.ConsistencyReview`, `schema.Decision`, `schema.DirectorDecision`, `schema.Scene`.
- Produces: `GeminiDirectorAgent(model_name="gemini-3.6-flash", api_key=None, client=None, base_url=None)` with `.run(scene: Scene, review: ConsistencyReview) -> DirectorDecision` and `.estimate_cost() -> float`; `DirectorAgentError`; `DirectorVerdict`. Independent of Tasks 1–4.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_gemini_director_agent.py
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_director_agent import (
    DirectorAgentError,
    DirectorVerdict,
    GeminiDirectorAgent,
)
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.schema import ConsistencyReview, Scene, Storyboard


def _scene(retry_count: int = 0, max_retries: int = 3) -> Scene:
    return Scene(
        scene_id="scene_01", beat_id="conflict", order=1, duration_sec=6,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        retry_count=retry_count, max_retries=max_retries,
    )


def _fake_interaction(output_text: str) -> SimpleNamespace:
    return SimpleNamespace(output_text=output_text)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiDirectorAgent()


def test_default_model_name_is_gemini_3_6_flash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiDirectorAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.6-flash"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiDirectorAgent(model_name="custom-director", client=MagicMock())

    assert agent.model_name == "custom-director"


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiDirectorAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.03
    assert agent.estimate_cost() == GeminiDirectorAgent.ESTIMATED_COST_USD


def test_run_honors_llm_decision_when_under_retry_cap(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    verdict = DirectorVerdict(decision="regenerate", feedback="색감이 어색함")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(verdict.model_dump_json())
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["색감 불일치"])

    decision = agent.run(_scene(retry_count=1, max_retries=3), review)

    assert decision.decision == "regenerate"
    assert decision.feedback == "색감이 어색함"
    assert decision.decided_by == agent.model_name


def test_run_forces_reject_when_retries_exhausted_regardless_of_llm_verdict(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    verdict = DirectorVerdict(decision="regenerate", feedback="한 번 더 시도해볼만함")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(verdict.model_dump_json())
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["색감 불일치"])

    decision = agent.run(_scene(retry_count=3, max_retries=3), review)

    assert decision.decision == "reject"
    assert decision.feedback == "한 번 더 시도해볼만함"


def test_run_still_calls_llm_when_retries_exhausted(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    verdict = DirectorVerdict(decision="accept", feedback="ok")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(verdict.model_dump_json())
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=True, issues=[])

    agent.run(_scene(retry_count=3, max_retries=3), review)

    assert client.interactions.create.called


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["issue"])

    with pytest.raises(DirectorAgentError):
        agent.run(_scene(), review)


def test_run_wraps_malformed_json_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["issue"])

    with pytest.raises(DirectorAgentError):
        agent.run(_scene(), review)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_gemini_director_agent.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_draft_pipeline/agents/gemini_director_agent.py
from pydantic import BaseModel

from ..schema import ConsistencyReview, Decision, DirectorDecision, Scene
from .gemini_agent_base import BaseGeminiAgent


def _build_input(scene: Scene, review: ConsistencyReview) -> str:
    issues = "; ".join(review.issues) or "none"
    return (
        "You are the creative director for a game marketing video draft. You "
        "decide whether a generated scene image should be accepted, "
        "regenerated, or rejected outright, based on a consistency review.\n\n"
        f"Scene: {scene.scene_id} ({scene.beat_id})\n"
        f"Review passed: {review.passed}\n"
        f"Review issues: {issues}\n"
        f"Retry count so far: {scene.retry_count} / max {scene.max_retries}\n"
        "Decide: accept (image is usable as-is), regenerate (image should be "
        "attempted again), or reject (give up on this scene). Give a short "
        "reason in feedback."
    )


class DirectorAgentError(Exception):
    pass


class DirectorVerdict(BaseModel):
    decision: Decision
    feedback: str | None = None


class GeminiDirectorAgent(BaseGeminiAgent):
    error_cls = DirectorAgentError
    ESTIMATED_COST_USD = 0.03

    def __init__(
        self,
        model_name: str = "gemini-3.6-flash",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision:
        input_content = [{"type": "text", "text": _build_input(scene, review)}]
        verdict = self._structured_interaction(input_content, DirectorVerdict)
        decision = verdict.decision
        if scene.retry_count >= scene.max_retries:
            decision = "reject"
        return DirectorDecision(decision=decision, feedback=verdict.feedback, decided_by=self.model_name)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_gemini_director_agent.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/gemini_director_agent.py tests/agents/test_gemini_director_agent.py
git commit -m "feat: add GeminiDirectorAgent"
```

---

### Task 6: Correct `GeminiReviewAgent`/`GeminiImageEditAgent` model defaults

**Files:**
- Modify: `src/video_draft_pipeline/agents/gemini_review_agent.py`
- Modify: `src/video_draft_pipeline/agents/gemini_image_edit_agent.py`
- Modify: `tests/agents/test_gemini_review_agent.py`
- Modify: `tests/agents/test_gemini_image_edit_agent.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `GeminiReviewAgent`'s default `model_name` becomes `"gemini-3.6-flash"` (was an image-generation model with no structured-output support — see spec Context); `GeminiImageEditAgent`'s default `model_name` becomes `"gemini-3-pro-image"` and `ESTIMATED_COST_USD` becomes `0.134`. Both drop their `base_url_config_field` override and the `base_url`-env-var test. Task 8 (factory) and Task 7 (config) depend on these corrected values.

- [ ] **Step 1: Update the failing/changed assertions in both test files**

In `tests/agents/test_gemini_review_agent.py`, replace:

```python
def test_default_model_name_is_gemini_3_pro_image(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(client=MagicMock())

    assert agent.model_name == "google/gemini-3-pro-image-preview"
```

with:

```python
def test_default_model_name_is_gemini_3_6_flash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiReviewAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.6-flash"
```

And update every other occurrence of `"google/gemini-3-pro-image-preview"` in that file's assertions (`test_run_calls_sdk_with_prompt_and_image`, `test_run_returns_consistency_review_from_passing_verdict` uses `model_name="custom-reviewer"` — unaffected) to `"gemini-3.6-flash"`. Delete `test_base_url_resolved_from_env_var` entirely (no `base_url_config_field` left to test).

In `tests/agents/test_gemini_image_edit_agent.py`, replace:

```python
def test_default_model_name_is_gemini_2_5_flash_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "google/gemini-2.5-flash-image"
```

with:

```python
def test_default_model_name_is_gemini_3_pro_image(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "gemini-3-pro-image"
```

Replace:

```python
def test_estimate_cost_returns_fixed_constant(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.estimate_cost() == 0.039
    assert agent.estimate_cost() == GeminiImageEditAgent.ESTIMATED_COST_USD
```

with:

```python
def test_estimate_cost_returns_fixed_constant(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiImageEditAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.estimate_cost() == 0.134
    assert agent.estimate_cost() == GeminiImageEditAgent.ESTIMATED_COST_USD
```

And update `test_run_calls_sdk_with_feedback_and_prior_image`/`test_run_writes_edited_image_and_returns_candidate`'s assertions of `"google/gemini-2.5-flash-image"` to `"gemini-3-pro-image"`. Delete `test_base_url_resolved_from_env_var` entirely.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_gemini_review_agent.py tests/agents/test_gemini_image_edit_agent.py -v`
Expected: FAIL (assertions against the old default strings)

- [ ] **Step 3: Update both agent files**

In `src/video_draft_pipeline/agents/gemini_review_agent.py`, change:

```python
class GeminiReviewAgent(BaseGeminiAgent):
    error_cls = ReviewAgentError
    ESTIMATED_COST_USD = 0.02
    base_url_config_field = "review_base_url"

    def __init__(self, model_name: str = "google/gemini-3-pro-image-preview", api_key: str | None = None, client=None, base_url: str | None = None):
        super().__init__(model_name, api_key, client, base_url)
```

to:

```python
class GeminiReviewAgent(BaseGeminiAgent):
    error_cls = ReviewAgentError
    ESTIMATED_COST_USD = 0.02

    def __init__(self, model_name: str = "gemini-3.6-flash", api_key: str | None = None, client=None, base_url: str | None = None):
        super().__init__(model_name, api_key, client, base_url)
```

In `src/video_draft_pipeline/agents/gemini_image_edit_agent.py`, change:

```python
class GeminiImageEditAgent(BaseGeminiAgent):
    error_cls = ImageEditAgentError
    ESTIMATED_COST_USD = 0.039
    base_url_config_field = "image_edit_base_url"

    def __init__(
        self,
        model_name: str = "google/gemini-2.5-flash-image",
        output_dir: str | Path = "media",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
```

to:

```python
class GeminiImageEditAgent(BaseGeminiAgent):
    error_cls = ImageEditAgentError
    ESTIMATED_COST_USD = 0.134

    def __init__(
        self,
        model_name: str = "gemini-3-pro-image",
        output_dir: str | Path = "media",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_gemini_review_agent.py tests/agents/test_gemini_image_edit_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/gemini_review_agent.py src/video_draft_pipeline/agents/gemini_image_edit_agent.py tests/agents/test_gemini_review_agent.py tests/agents/test_gemini_image_edit_agent.py
git commit -m "fix: correct GeminiReviewAgent/GeminiImageEditAgent model defaults for direct Gemini calls"
```

---

### Task 7: Config layer (`ModelConfig`/`ApiKeys`)

**Files:**
- Modify: `src/video_draft_pipeline/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ModelConfig` with all-Gemini defaults (`planning_model="gemini-3.1-pro-preview"`, `storyboard_model="gemini-3.6-flash"`, `prompt_model="gemini-3.5-flash-lite"`, `image_model="gemini-3.1-flash-image"`, `image_edit_model="gemini-3-pro-image"`, `review_model="gemini-3.6-flash"`, `director_model="gemini-3.6-flash"`, `render_backend="veo-3.1-fast"` unchanged); `ApiKeys(gemini_api_key, veo_api_key, ltx_api_key)` only. Task 8 (factory) consumes this `ModelConfig`/`ApiKeys` shape directly.

- [ ] **Step 1: Rewrite `tests/test_config.py`**

```python
# tests/test_config.py
from video_draft_pipeline.config import ModelConfig, load_api_keys


def test_model_config_defaults():
    cfg = ModelConfig()
    assert cfg.planning_model == "gemini-3.1-pro-preview"
    assert cfg.storyboard_model == "gemini-3.6-flash"
    assert cfg.prompt_model == "gemini-3.5-flash-lite"
    assert cfg.image_model == "gemini-3.1-flash-image"
    assert cfg.image_edit_model == "gemini-3-pro-image"
    assert cfg.review_model == "gemini-3.6-flash"
    assert cfg.director_model == "gemini-3.6-flash"
    assert cfg.render_backend == "veo-3.1-fast"


def test_load_api_keys_reads_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("VEO_API_KEY", raising=False)
    monkeypatch.delenv("LTX_API_KEY", raising=False)

    keys = load_api_keys()

    assert keys.gemini_api_key == "test-gemini-key"
    assert keys.veo_api_key is None
    assert keys.ltx_api_key is None


def test_load_api_keys_reads_veo_api_key(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "test-veo-key")

    keys = load_api_keys()

    assert keys.veo_api_key == "test-veo-key"


def test_load_api_keys_reads_ltx_api_key(monkeypatch):
    monkeypatch.setenv("LTX_API_KEY", "test-ltx-key")

    keys = load_api_keys()

    assert keys.ltx_api_key == "test-ltx-key"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (`ModelConfig` still has old defaults, `ApiKeys` still has old fields)

- [ ] **Step 3: Rewrite `src/video_draft_pipeline/config.py`**

```python
# src/video_draft_pipeline/config.py
import os
from dataclasses import dataclass


@dataclass
class ModelConfig:
    planning_model: str = "gemini-3.1-pro-preview"
    storyboard_model: str = "gemini-3.6-flash"
    prompt_model: str = "gemini-3.5-flash-lite"
    image_model: str = "gemini-3.1-flash-image"
    image_edit_model: str = "gemini-3-pro-image"
    review_model: str = "gemini-3.6-flash"
    director_model: str = "gemini-3.6-flash"
    render_backend: str = "veo-3.1-fast"


@dataclass
class ApiKeys:
    gemini_api_key: str | None = None
    veo_api_key: str | None = None
    ltx_api_key: str | None = None


def load_api_keys() -> ApiKeys:
    return ApiKeys(
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        veo_api_key=os.environ.get("VEO_API_KEY"),
        ltx_api_key=os.environ.get("LTX_API_KEY"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/config.py tests/test_config.py
git commit -m "feat: switch ModelConfig/ApiKeys to all-Gemini defaults"
```

---

### Task 8: Factory rewrite + protocol conformance

**Files:**
- Modify: `src/video_draft_pipeline/agents/factory.py`
- Modify: `tests/agents/test_factory.py`
- Modify: `tests/agents/test_protocols.py`

**Interfaces:**
- Consumes: `GeminiPlanningAgent`, `GeminiStoryboardAgent`, `GeminiPromptAgent`, `GeminiImageAgent`, `GeminiDirectorAgent` (Tasks 1–5); corrected `GeminiReviewAgent`/`GeminiImageEditAgent` (Task 6); `ModelConfig` (Task 7).
- Produces: `build_real_agents(gemini_api_key=None, output_dir="media", model_config=None, gemini_client=None) -> dict[str, object]` returning exactly the 7 keys `planning_agent`/`storyboard_agent`/`prompt_agent`/`image_agent`/`review_agent`/`director_agent`/`image_edit_agent`.

This task depends on Tasks 1–7 all being complete (it imports every new/corrected class). Run it last among Tasks 1–8.

- [ ] **Step 1: Rewrite `tests/agents/test_factory.py`**

```python
# tests/agents/test_factory.py
import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.agents.gemini_director_agent import DirectorVerdict
from video_draft_pipeline.agents.gemini_storyboard_agent import SceneDraft, StoryboardDraft
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.config import ModelConfig
from video_draft_pipeline.orchestrator import run_pipeline
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput, Prompts


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        build_real_agents(output_dir=tmp_path / "media")


def test_explicit_api_key_threaded_to_all_agents(tmp_path):
    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key",
        gemini_client=MagicMock(),
        output_dir=tmp_path / "media",
    )

    assert agents["planning_agent"].api_key == "explicit-gemini-key"
    assert agents["storyboard_agent"].api_key == "explicit-gemini-key"
    assert agents["prompt_agent"].api_key == "explicit-gemini-key"
    assert agents["image_agent"].api_key == "explicit-gemini-key"
    assert agents["review_agent"].api_key == "explicit-gemini-key"
    assert agents["director_agent"].api_key == "explicit-gemini-key"
    assert agents["image_edit_agent"].api_key == "explicit-gemini-key"


def test_returns_exactly_the_seven_expected_keys(tmp_path):
    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key", gemini_client=MagicMock(), output_dir=tmp_path / "media"
    )

    assert set(agents.keys()) == {
        "planning_agent", "storyboard_agent", "prompt_agent", "image_agent",
        "review_agent", "director_agent", "image_edit_agent",
    }


def test_custom_model_config_threaded_to_each_agent(tmp_path):
    model_config = ModelConfig(
        planning_model="custom-planner", storyboard_model="custom-storyboarder",
        prompt_model="custom-prompter", image_model="custom-imager",
        review_model="custom-reviewer", director_model="custom-director",
        image_edit_model="custom-image-editor",
    )

    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key", gemini_client=MagicMock(),
        output_dir=tmp_path / "media", model_config=model_config,
    )

    assert agents["planning_agent"].model_name == "custom-planner"
    assert agents["storyboard_agent"].model_name == "custom-storyboarder"
    assert agents["prompt_agent"].model_name == "custom-prompter"
    assert agents["image_agent"].model_name == "custom-imager"
    assert agents["review_agent"].model_name == "custom-reviewer"
    assert agents["director_agent"].model_name == "custom-director"
    assert agents["image_edit_agent"].model_name == "custom-image-editor"


def test_output_dir_threaded_to_image_agents(tmp_path):
    custom_dir = tmp_path / "custom-media"

    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key", gemini_client=MagicMock(), output_dir=custom_dir
    )

    assert agents["image_agent"].output_dir == custom_dir
    assert agents["image_edit_agent"].output_dir == custom_dir
    assert custom_dir.is_dir()


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
                beat_id=beat_id, camera="cam", subject="subj", action="act", setting="set",
                required_elements=[], duration_weight=1,
            )
            for beat_id in ("setup", "conflict", "climax", "resolution")
        ]
    )
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")
    director_verdict = DirectorVerdict(decision="accept", feedback="ok")

    call_count = {"n": 0}

    def fake_create(*, model, input, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return SimpleNamespace(output_text=narrative.model_dump_json())
        if call_count["n"] == 2:
            return SimpleNamespace(output_text=draft.model_dump_json())
        if call_count["n"] == 3:
            return SimpleNamespace(output_text=prompts.model_dump_json())
        if call_count["n"] == 4:
            image_data = base64.b64encode(b"fake-image-bytes").decode("utf-8")
            return SimpleNamespace(output_image=SimpleNamespace(data=image_data))
        if call_count["n"] == 5:
            return SimpleNamespace(output_text='{"passed": true, "issues": []}')
        return SimpleNamespace(output_text=director_verdict.model_dump_json())

    shared_gemini_client = MagicMock()
    shared_gemini_client.interactions.create.side_effect = fake_create

    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event")

    project = run_pipeline(
        project_input,
        **build_real_agents(
            gemini_api_key="test-key", gemini_client=shared_gemini_client, output_dir=tmp_path / "media"
        ),
    )

    assert len(project.scenes) == 4
    assert project.scenes[0].render is not None
    assert project.scenes[0].candidates[-1].consistency_review.passed is True
    assert project.scenes[0].candidates[-1].director_decision.decision == "accept"
```

- [ ] **Step 2: Add protocol conformance checks to `tests/agents/test_protocols.py`**

Add these imports and tests alongside the existing ones (do not remove the existing Elice-backed conformance checks — both sets of agents must satisfy the same protocols):

```python
from video_draft_pipeline.agents.gemini_director_agent import GeminiDirectorAgent
from video_draft_pipeline.agents.gemini_image_agent import GeminiImageAgent
from video_draft_pipeline.agents.gemini_planning_agent import GeminiPlanningAgent
from video_draft_pipeline.agents.gemini_prompt_agent import GeminiPromptAgent
from video_draft_pipeline.agents.gemini_storyboard_agent import GeminiStoryboardAgent


def test_gemini_planning_agent_satisfies_protocol():
    assert isinstance(GeminiPlanningAgent(api_key="test-key"), PlanningAgentProtocol)


def test_gemini_storyboard_agent_satisfies_protocol():
    assert isinstance(GeminiStoryboardAgent(api_key="test-key"), StoryboardAgentProtocol)


def test_gemini_prompt_agent_satisfies_protocol():
    assert isinstance(GeminiPromptAgent(api_key="test-key"), PromptAgentProtocol)


def test_gemini_image_agent_satisfies_protocol(tmp_path):
    assert isinstance(
        GeminiImageAgent(api_key="test-key", output_dir=tmp_path / "media"), ImageAgentProtocol
    )


def test_gemini_director_agent_satisfies_protocol():
    assert isinstance(GeminiDirectorAgent(api_key="test-key"), DirectorAgentProtocol)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/agents/test_factory.py tests/agents/test_protocols.py -v`
Expected: FAIL (`build_real_agents` still has the old signature; new protocol test imports fail)

- [ ] **Step 4: Rewrite `src/video_draft_pipeline/agents/factory.py`**

```python
# src/video_draft_pipeline/agents/factory.py
from pathlib import Path

from google import genai

from ..config import ModelConfig
from .gemini_director_agent import GeminiDirectorAgent
from .gemini_image_agent import GeminiImageAgent
from .gemini_image_edit_agent import GeminiImageEditAgent
from .gemini_planning_agent import GeminiPlanningAgent
from .gemini_prompt_agent import GeminiPromptAgent
from .gemini_review_agent import GeminiReviewAgent
from .gemini_storyboard_agent import GeminiStoryboardAgent


def build_real_agents(
    gemini_api_key: str | None = None,
    output_dir: str | Path = "media",
    model_config: ModelConfig | None = None,
    gemini_client: genai.Client | None = None,
) -> dict[str, object]:
    models = model_config or ModelConfig()
    return {
        "planning_agent": GeminiPlanningAgent(models.planning_model, api_key=gemini_api_key, client=gemini_client),
        "storyboard_agent": GeminiStoryboardAgent(models.storyboard_model, api_key=gemini_api_key, client=gemini_client),
        "prompt_agent": GeminiPromptAgent(models.prompt_model, api_key=gemini_api_key, client=gemini_client),
        "image_agent": GeminiImageAgent(models.image_model, output_dir=output_dir, api_key=gemini_api_key, client=gemini_client),
        "review_agent": GeminiReviewAgent(models.review_model, api_key=gemini_api_key, client=gemini_client),
        "director_agent": GeminiDirectorAgent(models.director_model, api_key=gemini_api_key, client=gemini_client),
        "image_edit_agent": GeminiImageEditAgent(models.image_edit_model, output_dir=output_dir, api_key=gemini_api_key, client=gemini_client),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/agents/test_factory.py tests/agents/test_protocols.py -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: PASS, all tests green (no leftover references to removed `openai_api_key`/`nemotron_api_key`/`ApiKeys` fields anywhere)

- [ ] **Step 7: Commit**

```bash
git add src/video_draft_pipeline/agents/factory.py tests/agents/test_factory.py tests/agents/test_protocols.py
git commit -m "feat: rewire build_real_agents to construct all-Gemini agents"
```

---

### Task 9: README / `.env.example`

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: nothing new (documentation only).
- Produces: nothing consumed by other tasks — last task in the plan.

- [ ] **Step 1: Update `.env.example`**

Replace the full contents with:

```bash
# Reference only — this file is NOT auto-loaded (no python-dotenv dependency).
# Export these into your shell environment; config.load_api_keys() reads os.environ.
#
# This branch (gemini-unification) calls Gemini directly with your own Google
# AI Studio key — no Elice proxy, no per-stage base URLs. All 5 previously
# Elice-proxied agents (planning/storyboard/prompt/image/director) plus the
# 2 that were already direct (review/image_edit) now share this one key.
GEMINI_API_KEY=

# Veo 3.1 and LTX are accessed directly against their own APIs, billed out of
# pocket, separate from GEMINI_API_KEY. LTX isn't in Elice's catalog at all.
VEO_API_KEY=
LTX_API_KEY=
```

- [ ] **Step 2: Update README's env var and "Real agent injection" sections**

Read `README.md` first to find the exact current line ranges (env var block around lines 39-55, "Real agent injection" section starting at line 73). Replace the env var export block:

```bash
export OPENAI_API_KEY=...      # PowerShell: $env:OPENAI_API_KEY = "..."
export GEMINI_API_KEY=...
export NEMOTRON_API_KEY=...
export VEO_API_KEY=...
export LTX_API_KEY=...

# Optional per-stage Elice proxy base URLs...
export OPENAI_PLANNING_BASE_URL=...
export OPENAI_STORYBOARD_BASE_URL=...
export OPENAI_PROMPT_BASE_URL=...
export OPENAI_IMAGE_BASE_URL=...
export GEMINI_IMAGE_EDIT_BASE_URL=...
export GEMINI_REVIEW_BASE_URL=...
export NEMOTRON_DIRECTOR_BASE_URL=...
```

with:

```bash
export GEMINI_API_KEY=...      # PowerShell: $env:GEMINI_API_KEY = "..."
export VEO_API_KEY=...
export LTX_API_KEY=...
```

And update the `build_real_agents` usage examples:

```python
run_pipeline(project_input, **build_real_agents(gemini_api_key="..."))
```

```python
**build_real_agents(gemini_api_key="...", model_config=cfg),
```

Add a short paragraph near the top of the "Real agent injection" section:

> **Branch note:** on `gemini-unification`, every agent (`planning`, `storyboard`, `prompt`, `image`, `image_edit`, `review`, `director`) calls Gemini directly with `GEMINI_API_KEY` — no Elice proxy. This differs from `master`, where 5 of the 7 stages route through Elice's OpenAI-compatible gateway. See `docs/superpowers/specs/2026-08-03-gemini-unification-design.md` for why.

- [ ] **Step 3: Verify no stale references remain**

Run: `grep -rn "OPENAI_API_KEY\|NEMOTRON_API_KEY\|_BASE_URL" README.md .env.example`
Expected: no matches (both files fully updated)

- [ ] **Step 4: Commit**

```bash
git add README.md .env.example
git commit -m "docs: update README/.env.example for all-Gemini branch"
```

---

## Self-Review Notes

- **Spec coverage:** all 7 agents (5 new + 2 corrected) covered (Tasks 1–6); config/factory covered (Tasks 7–8); docs covered (Task 9). The spec's "text-only agents build a single input string" design point is implemented identically in Tasks 1, 2, 3, 5. The spec's `GeminiDirectorAgent` safety-invariant requirement is preserved verbatim in Task 5. No spec section without a corresponding task.
- **Placeholder scan:** no TBD/TODO; every step has real, complete code.
- **Type consistency:** `_build_input`/`_build_messages` naming is consistent per-agent (each new file defines its own local `_build_input`, matching the OpenAI-family convention of local `_build_messages`). `GeminiStoryboardAgent`'s `SceneDraft`/`StoryboardDraft`/`_drafts_to_scenes` names match `OpenAIStoryboardAgent`'s exactly (mechanical port, no renaming). `build_real_agents()`'s 7 return keys are identical across Task 8's implementation and its test's key-set assertion.
- **Task 8's fake `run_pipeline` test**: relies on `client.interactions.create` being called in a fixed order (planning → storyboard → prompt → image → review → director) matching `run_pipeline`'s actual call sequence (`orchestrator.py:95-119`) for a single-scene-retry-free run. If the implementer finds the call order doesn't match in practice, they should switch the fake to dispatch on `response_format`-equivalent (inspecting `input` text content or a schema hint) rather than call order — flagged here so it's not a surprise, not blocking.
