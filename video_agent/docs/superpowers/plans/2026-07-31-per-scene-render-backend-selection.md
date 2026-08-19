# Per-Scene Render Backend Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `VideoRenderAgent` route a scene to a different `RenderBackend` based on `scene.beat_id`, so a project can spend on a paid/high-quality backend for its highest-value beats (`climax`/`resolution`) and a free backend for the rest (`setup`/`conflict`), while staying fully backward compatible with today's single-backend usage.

**Architecture:** `VideoRenderAgent` gains an optional `backend_by_beat: dict[BeatId, RenderBackend] | None = None` constructor param; `backend` stays required and doubles as the fallback for any beat not in the map. A single `_select_backend(scene)` helper method feeds both the pre-charge cost estimate and the actual render, so there's never drift between what was budget-checked and what actually ran. A small `beat_backend_map(paid_backend, free_backend)` convenience function encodes the one specific split this plan locks in. `run_pipeline` gains one new, purely additive `render_backend_by_beat` param threaded straight into `VideoRenderAgent`. No changes to the `RenderBackend` protocol or any existing backend class.

**Tech Stack:** Python 3.11+, pytest, `unittest.mock` not needed (plain fake test doubles, matching this file's existing style).

## Global Constraints

- Scope is the selection mechanism only. `SelfHostedBackend`'s real implementation is out of scope — this plan works against any `RenderBackend`-conforming instance, real or fake/stub.
- No changes to the `RenderBackend` protocol (`render_backends/base.py`) or to `VeoBackend`/`StubRenderBackend`/`SelfHostedBackend` — none of them need to know about beat-based routing; that's `VideoRenderAgent`'s job alone.
- `backend_by_beat=None` (the default) must be a complete no-op: `VideoRenderAgent`'s existing single-backend behavior is unchanged, and every existing test in `tests/agents/test_video_render_agent.py` that constructs it with only `backend=` must keep passing completely unmodified.
- `beat_backend_map()` is a pure convenience helper for one specific split (`climax`/`resolution` → paid, `setup`/`conflict` → free). `backend_by_beat` itself stays a plain arbitrary `dict[BeatId, RenderBackend]` — nothing forces callers through the helper.
- No `agents/factory.py` changes — the render stage has never been part of `build_real_agents()`; it's injected separately via `run_pipeline`'s own params.
- No live-API tests — the mechanism itself never talks to a real backend.
- All existing tests must keep passing (265 as of the last branch) — this plan is purely additive, nothing existing needs updating.

---

### Task 1: `VideoRenderAgent` selection logic + `beat_backend_map()` helper

**Files:**
- Modify: `src/video_draft_pipeline/agents/video_render_agent.py`
- Test: `tests/agents/test_video_render_agent.py`

**Interfaces:**
- Consumes: `schema.BeatId`, `schema.Scene`, `schema.RenderResult`, `schema.Candidate` (already exist, unchanged), `render_backends.base.RenderBackend` (already exists, unchanged), `guards.budget_guard` (already exists, unchanged).
- Produces: `VideoRenderAgent(backend: RenderBackend, backend_by_beat: dict[BeatId, RenderBackend] | None = None)` with `run(scene, current_cost_usd, max_budget_usd) -> RenderResult` (unchanged return type/behavior when `backend_by_beat` is not given) and a new `_select_backend(scene) -> RenderBackend` method. `beat_backend_map(paid_backend: RenderBackend, free_backend: RenderBackend) -> dict[BeatId, RenderBackend]`, both in `video_draft_pipeline.agents.video_render_agent`. Task 2 consumes `VideoRenderAgent`'s new `backend_by_beat` param name exactly, and imports `beat_backend_map` for its own test.

- [ ] **Step 1: Write the failing tests**

Replace `tests/agents/test_video_render_agent.py` in full:

```python
import pytest

from video_draft_pipeline.schema import BeatId, RenderResult, Scene, Storyboard, Candidate
from video_draft_pipeline.guards import BudgetExceededError
from video_draft_pipeline.render_backends.stub_backend import StubRenderBackend
from video_draft_pipeline.agents.video_render_agent import VideoRenderAgent, beat_backend_map


def _scene_with_accepted_candidate(duration_sec: float = 6.0, beat_id: BeatId = "conflict") -> Scene:
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")
    scene = Scene(
        scene_id="scene_01",
        beat_id=beat_id,
        order=1,
        duration_sec=duration_sec,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        candidates=[candidate],
        accepted_candidate_id="c1",
    )
    scene.prompts = None
    return scene


def test_video_render_agent_renders_under_budget():
    agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    result = agent.run(_scene_with_accepted_candidate(6.0), current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.status == "done"
    assert result.cost_usd == 0.60


def test_video_render_agent_raises_when_over_budget():
    agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(BudgetExceededError):
        agent.run(_scene_with_accepted_candidate(6.0), current_cost_usd=4.5, max_budget_usd=5.0)


def test_video_render_agent_raises_without_accepted_candidate():
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6.0,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
    )
    agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(ValueError):
        agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)


def test_video_render_agent_raises_when_accepted_candidate_not_in_list():
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6.0,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        candidates=[candidate],
        accepted_candidate_id="does-not-exist",
    )
    agent = VideoRenderAgent(backend=StubRenderBackend(tier="veo-3.1-fast"))

    with pytest.raises(ValueError):
        agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)


class _MappedBackend:
    def __init__(self, cost: float = 0.0):
        self.cost = cost
        self.render_called = False

    def estimate_cost(self, duration_sec):
        return self.cost

    def render(self, candidate, motion_prompt, duration_sec):
        self.render_called = True
        return RenderResult(backend="veo-3.1-lite", status="done", clip_url="fake://mapped", cost_usd=self.cost)


class _DefaultBackend:
    def __init__(self, cost: float = 0.0):
        self.cost = cost
        self.render_called = False

    def estimate_cost(self, duration_sec):
        return self.cost

    def render(self, candidate, motion_prompt, duration_sec):
        self.render_called = True
        return RenderResult(backend="veo-3.1-standard", status="done", clip_url="fake://default", cost_usd=self.cost)


def test_run_routes_to_mapped_backend_for_beat_in_map():
    mapped = _MappedBackend()
    default = _DefaultBackend()
    agent = VideoRenderAgent(backend=default, backend_by_beat={"climax": mapped})
    scene = _scene_with_accepted_candidate(6.0, beat_id="climax")

    result = agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.backend == "veo-3.1-lite"
    assert mapped.render_called is True
    assert default.render_called is False


def test_run_falls_back_to_default_backend_when_beat_not_in_map():
    mapped = _MappedBackend()
    default = _DefaultBackend()
    agent = VideoRenderAgent(backend=default, backend_by_beat={"climax": mapped})
    scene = _scene_with_accepted_candidate(6.0, beat_id="setup")

    result = agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.backend == "veo-3.1-standard"
    assert default.render_called is True
    assert mapped.render_called is False


def test_run_falls_back_to_default_backend_when_backend_by_beat_not_given():
    default = _DefaultBackend()
    agent = VideoRenderAgent(backend=default)
    scene = _scene_with_accepted_candidate(6.0, beat_id="climax")

    result = agent.run(scene, current_cost_usd=0.0, max_budget_usd=5.0)

    assert result.backend == "veo-3.1-standard"
    assert default.render_called is True


def test_run_charges_budget_guard_against_the_selected_backend_not_the_default():
    expensive_mapped = _MappedBackend(cost=100.0)
    cheap_default = _DefaultBackend(cost=0.0)
    agent = VideoRenderAgent(backend=cheap_default, backend_by_beat={"climax": expensive_mapped})
    scene = _scene_with_accepted_candidate(6.0, beat_id="climax")

    with pytest.raises(BudgetExceededError):
        agent.run(scene, current_cost_usd=0.0, max_budget_usd=1.0)

    assert expensive_mapped.render_called is False
    assert cheap_default.render_called is False


def test_beat_backend_map_maps_climax_and_resolution_to_paid_setup_and_conflict_to_free():
    paid = _MappedBackend()
    free = _DefaultBackend()

    mapping = beat_backend_map(paid_backend=paid, free_backend=free)

    assert mapping == {
        "climax": paid,
        "resolution": paid,
        "setup": free,
        "conflict": free,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_video_render_agent.py -v`
Expected: FAIL — `VideoRenderAgent` doesn't accept `backend_by_beat` yet, `beat_backend_map` doesn't exist, `_scene_with_accepted_candidate` doesn't accept `beat_id` yet.

- [ ] **Step 3: Write the implementation**

Replace `src/video_draft_pipeline/agents/video_render_agent.py` in full:

```python
from ..schema import BeatId, Scene, RenderResult, Candidate
from ..guards import budget_guard
from ..render_backends.base import RenderBackend


class VideoRenderAgent:
    def __init__(
        self,
        backend: RenderBackend,
        backend_by_beat: dict[BeatId, RenderBackend] | None = None,
    ):
        self.backend = backend
        self.backend_by_beat = backend_by_beat or {}

    def run(self, scene: Scene, current_cost_usd: float, max_budget_usd: float) -> RenderResult:
        backend = self._select_backend(scene)
        estimated_cost = backend.estimate_cost(scene.duration_sec)
        budget_guard(current_cost_usd, estimated_cost, max_budget_usd)

        candidate = self._accepted_candidate(scene)
        motion_prompt = scene.prompts.video_motion_prompt if scene.prompts else ""
        return backend.render(
            candidate=candidate,
            motion_prompt=motion_prompt,
            duration_sec=scene.duration_sec,
        )

    def _select_backend(self, scene: Scene) -> RenderBackend:
        return self.backend_by_beat.get(scene.beat_id, self.backend)

    def _accepted_candidate(self, scene: Scene) -> Candidate:
        if scene.accepted_candidate_id is None:
            raise ValueError(f"Scene {scene.scene_id} has no accepted candidate")
        for candidate in scene.candidates:
            if candidate.candidate_id == scene.accepted_candidate_id:
                return candidate
        raise ValueError(
            f"Accepted candidate {scene.accepted_candidate_id} not found on scene {scene.scene_id}"
        )


def beat_backend_map(paid_backend: RenderBackend, free_backend: RenderBackend) -> dict[BeatId, RenderBackend]:
    return {
        "climax": paid_backend,
        "resolution": paid_backend,
        "setup": free_backend,
        "conflict": free_backend,
    }
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/video_render_agent.py tests/agents/test_video_render_agent.py
git commit -m "feat: add beat-based backend selection to VideoRenderAgent"
```

---

### Task 2: `run_pipeline` threading

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `VideoRenderAgent(backend, backend_by_beat=None)` (Task 1), `agents.video_render_agent.beat_backend_map` (Task 1), `schema.BeatId` (already exists).
- Produces: `run_pipeline(..., render_backend_by_beat: dict[BeatId, RenderBackend] | None = None) -> Project`. Nothing downstream in this plan consumes this further.

- [ ] **Step 1: Write the failing test**

In `tests/test_orchestrator.py`, add `RenderResult` to the existing `schema` import block:

```python
from video_draft_pipeline.schema import (
    Beat,
    Candidate,
    ConsistencyReview,
    DirectorDecision,
    Narrative,
    ProjectInput,
    Prompts,
    RenderResult,
    Scene,
    Storyboard,
)
```

Add an import for `beat_backend_map`:

```python
from video_draft_pipeline.agents.video_render_agent import beat_backend_map
```

Append at the end of the file:

```python
class FakePaidRenderBackend:
    def estimate_cost(self, duration_sec):
        return 0.0

    def render(self, candidate, motion_prompt, duration_sec):
        return RenderResult(backend="veo-3.1-standard", status="done", clip_url="fake://paid", cost_usd=0.0)


class FakeFreeRenderBackend:
    def estimate_cost(self, duration_sec):
        return 0.0

    def render(self, candidate, motion_prompt, duration_sec):
        return RenderResult(backend="self-hosted", status="done", clip_url="fake://free", cost_usd=0.0)


def test_run_pipeline_routes_scenes_by_beat_with_render_backend_by_beat():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )
    paid = FakePaidRenderBackend()
    free = FakeFreeRenderBackend()

    project = run_pipeline(
        project_input,
        render_backend_by_beat=beat_backend_map(paid_backend=paid, free_backend=free),
    )

    backend_by_beat_id = {scene.beat_id: scene.render.backend for scene in project.scenes}
    assert backend_by_beat_id["climax"] == "veo-3.1-standard"
    assert backend_by_beat_id["resolution"] == "veo-3.1-standard"
    assert backend_by_beat_id["setup"] == "self-hosted"
    assert backend_by_beat_id["conflict"] == "self-hosted"


def test_run_pipeline_ignores_render_backend_by_beat_when_not_given():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(project_input)

    assert project.scenes[0].render.clip_url.startswith("stub://veo/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL — `run_pipeline` doesn't accept `render_backend_by_beat` yet, so `TypeError: run_pipeline() got an unexpected keyword argument`.

- [ ] **Step 3: Write the implementation**

In `src/video_draft_pipeline/orchestrator.py`, add `BeatId` to the schema import:

```python
from .schema import BeatId, Project, ProjectInput
```

change the `run_pipeline` signature:

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    render_backend_by_beat: dict[BeatId, RenderBackend] | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
    director_agent: DirectorAgentProtocol | None = None,
) -> Project:
```

and change the render-agent construction line:

```python
    backend = render_backend or StubRenderBackend(tier=models.render_backend)
    render_agent = VideoRenderAgent(backend=backend, backend_by_beat=render_backend_by_beat)
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: thread render_backend_by_beat through run_pipeline"
```

---

## Self-Review Notes

- **Spec coverage:** `VideoRenderAgent`'s selection logic and `beat_backend_map()` helper (Task 1), `run_pipeline` threading (Task 2) — every section of the approved spec is covered. The spec's "no `RenderBackend` protocol changes" and "no `factory.py` changes" non-goals are honored: neither task touches `render_backends/base.py`, any backend class, or `agents/factory.py`.
- **Placeholder scan:** no "TBD"/"handle appropriately"/"similar to Task N" phrasing; every step shows complete code.
- **Type consistency:** `backend_by_beat` parameter name and `dict[BeatId, RenderBackend]` type are identical between Task 1 (definition on `VideoRenderAgent`) and Task 2 (threading through `run_pipeline`, naming its own param `render_backend_by_beat` to match the existing `render_backend`/`render_backend_by_beat` pairing convention). `beat_backend_map`'s signature (`paid_backend`, `free_backend` keyword args) matches exactly between Task 1's definition and Task 2's test usage.
- **Backward compatibility, explicitly verified in both tasks:** Task 1's existing 4 tests (unchanged) prove `VideoRenderAgent(backend=...)` alone still works; Task 2's `test_run_pipeline_ignores_render_backend_by_beat_when_not_given` proves `run_pipeline` without the new param is unaffected.
