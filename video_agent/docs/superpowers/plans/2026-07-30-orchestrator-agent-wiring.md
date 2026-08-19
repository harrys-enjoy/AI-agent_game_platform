# Orchestrator Agent Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `run_pipeline()` optionally use the 4 real `OpenAI*Agent` implementations (Planning/Storyboard/Prompt/Image) in place of their stubs, per agent, per call, without changing default (fully offline, fully stub) behavior.

**Architecture:** Add a `Protocol` per ready agent (mirroring the existing `RenderBackend` Protocol pattern) so `run_pipeline`'s new parameters can be typed against a shape both the stub and the real `OpenAI*Agent` classes satisfy without any inheritance changes. Then add 4 new optional parameters to `run_pipeline`, each falling back to constructing the existing stub when not given — exactly how `render_backend` already works.

**Tech Stack:** Python 3.11+, Pydantic v2, `typing.Protocol` (`@runtime_checkable`), pytest.

## Global Constraints

- All 6 existing tests in `tests/test_orchestrator.py` must keep passing unmodified — no edits to their bodies.
- `run_pipeline()` must default to full stub behavior when no real agents are injected: no network calls, no API key required, deterministic output.
- No live-API or integration tests against real `OpenAI*Agent` classes. Use lightweight fake doubles (plain classes implementing `.run()`) that satisfy the protocol shape instead.
- `ReviewAgent`, `DirectorAgent`, `VideoRenderAgent`, and `VeoBackend` are out of scope — they stay stubs, untouched.
- No changes to `run_pipeline`'s control flow, guards (`duration_guard`/`budget_guard`), the retry loop, or cost tracking, beyond adding the 4 new optional parameters and their fallback-to-stub assignment.
- No new dependencies. Follow existing codebase conventions (Pydantic `BaseModel`/`Field`/`Literal`, `Protocol` for structural typing as already used by `RenderBackend`).

---

### Task 1: Agent Protocols

**Files:**
- Create: `src/video_draft_pipeline/agents/protocols.py`
- Test: `tests/agents/test_protocols.py`

**Interfaces:**
- Consumes: `PlanningAgent` (`src/video_draft_pipeline/agents/planning_agent.py`), `OpenAIPlanningAgent` (`src/video_draft_pipeline/agents/openai_planning_agent.py`), `StoryboardAgent`/`OpenAIStoryboardAgent`, `PromptAgent`/`OpenAIPromptAgent`, `ImageAgent`/`OpenAIImageAgent` — all already exist, all already have matching `run()` signatures between stub and real.
- Produces: `PlanningAgentProtocol`, `StoryboardAgentProtocol`, `PromptAgentProtocol`, `ImageAgentProtocol` — all in `video_draft_pipeline.agents.protocols`, all `@runtime_checkable` `Protocol` classes. Task 2 imports and uses these directly as parameter type hints.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_protocols.py`:

```python
from video_draft_pipeline.agents.image_agent import ImageAgent
from video_draft_pipeline.agents.openai_image_agent import OpenAIImageAgent
from video_draft_pipeline.agents.openai_planning_agent import OpenAIPlanningAgent
from video_draft_pipeline.agents.openai_prompt_agent import OpenAIPromptAgent
from video_draft_pipeline.agents.openai_storyboard_agent import OpenAIStoryboardAgent
from video_draft_pipeline.agents.planning_agent import PlanningAgent
from video_draft_pipeline.agents.prompt_agent import PromptAgent
from video_draft_pipeline.agents.protocols import (
    ImageAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    StoryboardAgentProtocol,
)
from video_draft_pipeline.agents.storyboard_agent import StoryboardAgent


def test_planning_agents_satisfy_protocol():
    assert isinstance(PlanningAgent(), PlanningAgentProtocol)
    assert isinstance(OpenAIPlanningAgent(api_key="test-key"), PlanningAgentProtocol)


def test_storyboard_agents_satisfy_protocol():
    assert isinstance(StoryboardAgent(), StoryboardAgentProtocol)
    assert isinstance(OpenAIStoryboardAgent(api_key="test-key"), StoryboardAgentProtocol)


def test_prompt_agents_satisfy_protocol():
    assert isinstance(PromptAgent(), PromptAgentProtocol)
    assert isinstance(OpenAIPromptAgent(api_key="test-key"), PromptAgentProtocol)


def test_image_agents_satisfy_protocol(tmp_path):
    assert isinstance(ImageAgent(), ImageAgentProtocol)
    assert isinstance(
        OpenAIImageAgent(api_key="test-key", output_dir=tmp_path / "media"),
        ImageAgentProtocol,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_protocols.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.protocols'`

- [ ] **Step 3: Write the implementation**

Create `src/video_draft_pipeline/agents/protocols.py`:

```python
from typing import Protocol, runtime_checkable

from ..schema import Candidate, Narrative, ProjectInput, Prompts, Scene


@runtime_checkable
class PlanningAgentProtocol(Protocol):
    def run(self, project_input: ProjectInput) -> Narrative: ...


@runtime_checkable
class StoryboardAgentProtocol(Protocol):
    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]: ...


@runtime_checkable
class PromptAgentProtocol(Protocol):
    def run(self, scene: Scene) -> Prompts: ...


@runtime_checkable
class ImageAgentProtocol(Protocol):
    def run(self, prompts: Prompts) -> Candidate: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_protocols.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/protocols.py tests/agents/test_protocols.py
git commit -m "feat: add Protocol types for stub/real agent interchangeability"
```

---

### Task 2: Wire per-agent injection into `run_pipeline`

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `PlanningAgentProtocol`, `StoryboardAgentProtocol`, `PromptAgentProtocol`, `ImageAgentProtocol` from `video_draft_pipeline.agents.protocols` (Task 1).
- Produces: `run_pipeline(project_input, render_backend=None, model_config=None, planning_agent=None, storyboard_agent=None, prompt_agent=None, image_agent=None) -> Project` — 4 new optional keyword parameters, each defaulting to `None` and falling back to the existing stub construction when not provided.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_orchestrator.py` (append after the existing tests; add these imports at the top alongside the existing ones):

```python
from video_draft_pipeline.schema import Beat, Narrative, Prompts, Scene, Storyboard
```

```python
class FakePlanningAgent:
    def run(self, project_input):
        return Narrative(
            beats=[Beat(beat_id="setup", description="fake-planning-marker", tone="calm")]
        )


def test_run_pipeline_injected_planning_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, planning_agent=FakePlanningAgent())

    assert len(project.narrative.beats) == 1
    assert project.narrative.beats[0].description == "fake-planning-marker"
    assert len(project.scenes) == 1


class FakeStoryboardAgent:
    def run(self, narrative, project_input):
        return [
            Scene(
                scene_id="fake_scene_injected",
                beat_id="setup",
                order=1,
                duration_sec=project_input.duration_sec,
                storyboard=Storyboard(
                    camera="fake-cam",
                    subject="fake-subj",
                    action="fake-action",
                    setting="fake-setting",
                ),
            )
        ]


def test_run_pipeline_injected_storyboard_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, storyboard_agent=FakeStoryboardAgent())

    assert len(project.scenes) == 1
    assert project.scenes[0].scene_id == "fake_scene_injected"


class FakePromptAgent:
    def run(self, scene):
        return Prompts(image_prompt="fake-prompt-marker", video_motion_prompt="fake-motion")


def test_run_pipeline_injected_prompt_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, prompt_agent=FakePromptAgent())

    assert project.scenes[0].prompts.image_prompt == "fake-prompt-marker"


class FakeImageAgent:
    def run(self, prompts):
        return Candidate(
            candidate_id="fake_cand_injected",
            image_url="fake://url",
            generated_by="fake-image-model",
        )


def test_run_pipeline_injected_image_agent_overrides_default():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input, image_agent=FakeImageAgent())

    candidate = project.scenes[0].candidates[-1]
    assert candidate.candidate_id == "fake_cand_injected"
    assert candidate.generated_by == "fake-image-model"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`
Expected: The 4 new tests FAIL with `TypeError: run_pipeline() got an unexpected keyword argument 'planning_agent'` (or `'storyboard_agent'`/`'prompt_agent'`/`'image_agent'`). The 6 pre-existing tests still PASS.

- [ ] **Step 3: Write the implementation**

In `src/video_draft_pipeline/orchestrator.py`, add the import (after the existing `render_backends` imports):

```python
from .agents.protocols import (
    ImageAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    StoryboardAgentProtocol,
)
```

Change the `run_pipeline` signature and the agent-construction block from:

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    model_config: ModelConfig | None = None,
) -> Project:
    models = model_config or ModelConfig()
    project = Project(project_id=f"proj_{uuid.uuid4().hex[:8]}", input=project_input)

    planning_agent = PlanningAgent(models.planning_model)
    storyboard_agent = StoryboardAgent(models.storyboard_model)
    prompt_agent = PromptAgent(models.prompt_model)
    image_agent = ImageAgent(models.image_model)
    review_agent = ReviewAgent(models.review_model)
    director_agent = DirectorAgent(models.director_model)
    backend = render_backend or VeoBackend(tier=models.render_backend)
    render_agent = VideoRenderAgent(backend=backend)
```

to:

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
) -> Project:
    models = model_config or ModelConfig()
    project = Project(project_id=f"proj_{uuid.uuid4().hex[:8]}", input=project_input)

    planning_agent = planning_agent or PlanningAgent(models.planning_model)
    storyboard_agent = storyboard_agent or StoryboardAgent(models.storyboard_model)
    prompt_agent = prompt_agent or PromptAgent(models.prompt_model)
    image_agent = image_agent or ImageAgent(models.image_model)
    review_agent = ReviewAgent(models.review_model)
    director_agent = DirectorAgent(models.director_model)
    backend = render_backend or VeoBackend(tier=models.render_backend)
    render_agent = VideoRenderAgent(backend=backend)
```

The rest of the function body (narrative/scene loop, guards, retry loop, cost tracking) is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS (10 passed — 6 pre-existing + 4 new)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`
Expected: All tests pass (previous total was 133; this plan adds 4 protocol tests + 4 injection tests, so expect 141 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: wire real-agent injection params into run_pipeline"
```

---

## Self-Review Notes

- **Spec coverage:** Selection mechanism (per-agent injection, defaulting to stub) → Task 2. Protocol typing for the 4 agents → Task 1. `run_pipeline` signature/body changes → Task 2. Testing (existing tests untouched, new fake-double injection tests, no live-API tests) → Task 2 steps 1–5. Non-goals (Review/Director/VideoRender untouched, no config/env switch, no external API exposure) — no task touches these, consistent with spec.
- **Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code; no "similar to Task N" shortcuts — Task 2's Storyboard/Prompt/Image fakes are each written out in full even though structurally similar.
- **Type consistency:** `run()` signatures in Task 1's protocols (`PlanningAgentProtocol.run(project_input) -> Narrative`, etc.) match both the existing stub classes and the parameter names/fallback logic used in Task 2 exactly. Fake test doubles in Task 2 implement the same `run()` shapes the protocols declare, so they satisfy the protocols structurally even though the tests don't assert `isinstance` on them (that assertion already lives in Task 1 against the real stub/OpenAI classes).
