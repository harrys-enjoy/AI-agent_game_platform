# Budget Tracking for Real Agent Calls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the budget-tracking gap flagged in the orchestrator-agent-wiring branch's final review — extend `budget_guard` coverage from render-only to all 4 real agents (Planning/Storyboard/Prompt/Image), so injecting any of them can never spend past `max_budget_usd` unnoticed.

**Architecture:** Each of the 4 agent Protocols gains an `estimate_cost() -> float` method. Stub agents return `0.0` (free); real `OpenAI*Agent` classes return a fixed per-call constant. `run_pipeline` gains a small `_charge` helper (guard-then-accumulate, mirroring the existing render-cost pattern) and calls it before each of the 4 agent calls.

**Tech Stack:** Python 3.11+, Pydantic v2, `typing.Protocol`, pytest, `unittest.mock.MagicMock`.

## Global Constraints

- Stub agents' `estimate_cost()` must return exactly `0.0` — this is what keeps every existing test's behavior unchanged when nothing real is injected.
- Real agent cost estimates are fixed flat constants, not live metering: `OpenAIPlanningAgent.ESTIMATED_COST_USD = 0.01`, `OpenAIStoryboardAgent.ESTIMATED_COST_USD = 0.01`, `OpenAIPromptAgent.ESTIMATED_COST_USD = 0.005`, `OpenAIImageAgent.ESTIMATED_COST_USD = 0.04`.
- The image-agent guard must run fresh on every retry attempt inside the scene loop, not just once per scene.
- The existing render-cost guard (`render_agent.run(scene, running_cost, project_input.max_budget_usd)`) is untouched.
- No live-API or integration tests. No new dependencies.
- All existing tests (145 as of the last branch) must keep passing — the 4 `FakePlanningAgent`/`FakeStoryboardAgent`/`FakePromptAgent`/`FakeImageAgent` doubles in `tests/test_orchestrator.py` need `estimate_cost()` added or they'll raise `AttributeError` once `run_pipeline` calls it unconditionally.

---

### Task 1: `estimate_cost()` on all 8 agent classes + protocols

**Files:**
- Modify: `src/video_draft_pipeline/agents/protocols.py`
- Modify: `src/video_draft_pipeline/agents/planning_agent.py`
- Modify: `src/video_draft_pipeline/agents/storyboard_agent.py`
- Modify: `src/video_draft_pipeline/agents/prompt_agent.py`
- Modify: `src/video_draft_pipeline/agents/image_agent.py`
- Modify: `src/video_draft_pipeline/agents/openai_planning_agent.py`
- Modify: `src/video_draft_pipeline/agents/openai_storyboard_agent.py`
- Modify: `src/video_draft_pipeline/agents/openai_prompt_agent.py`
- Modify: `src/video_draft_pipeline/agents/openai_image_agent.py`
- Test: `tests/agents/test_planning_agent.py`
- Test: `tests/agents/test_storyboard_agent.py`
- Test: `tests/agents/test_prompt_agent.py`
- Test: `tests/agents/test_image_agent.py`
- Test: `tests/agents/test_openai_planning_agent.py`
- Test: `tests/agents/test_openai_storyboard_agent.py`
- Test: `tests/agents/test_openai_prompt_agent.py`
- Test: `tests/agents/test_openai_image_agent.py`

**Interfaces:**
- Consumes: nothing new — all 8 classes already exist from prior branches.
- Produces: `estimate_cost(self) -> float` on `PlanningAgent`, `StoryboardAgent`, `PromptAgent`, `ImageAgent` (always `0.0`) and on `OpenAIPlanningAgent`, `OpenAIStoryboardAgent`, `OpenAIPromptAgent`, `OpenAIImageAgent` (each returns its own `ESTIMATED_COST_USD` class constant: `0.01`, `0.01`, `0.005`, `0.04` respectively). Task 2 calls `.estimate_cost()` on whatever agent instance `run_pipeline` is holding, real or stub, without needing to know which.

- [ ] **Step 1: Write the failing tests**

Append to `tests/agents/test_planning_agent.py`:

```python
def test_planning_agent_estimate_cost_is_zero():
    assert PlanningAgent().estimate_cost() == 0.0
```

Append to `tests/agents/test_storyboard_agent.py`:

```python
def test_storyboard_agent_estimate_cost_is_zero():
    assert StoryboardAgent().estimate_cost() == 0.0
```

Append to `tests/agents/test_prompt_agent.py`:

```python
def test_prompt_agent_estimate_cost_is_zero():
    assert PromptAgent().estimate_cost() == 0.0
```

Append to `tests/agents/test_image_agent.py`:

```python
def test_image_agent_estimate_cost_is_zero():
    assert ImageAgent().estimate_cost() == 0.0
```

Append to `tests/agents/test_openai_planning_agent.py` (the file already imports `MagicMock` and `OpenAIPlanningAgent`):

```python
def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPlanningAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.01
    assert agent.estimate_cost() == OpenAIPlanningAgent.ESTIMATED_COST_USD
```

Append to `tests/agents/test_openai_storyboard_agent.py` (already imports `MagicMock` and `OpenAIStoryboardAgent`):

```python
def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIStoryboardAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.01
    assert agent.estimate_cost() == OpenAIStoryboardAgent.ESTIMATED_COST_USD
```

Append to `tests/agents/test_openai_prompt_agent.py` (already imports `MagicMock` and `OpenAIPromptAgent`):

```python
def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIPromptAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.005
    assert agent.estimate_cost() == OpenAIPromptAgent.ESTIMATED_COST_USD
```

Append to `tests/agents/test_openai_image_agent.py` (already imports `MagicMock`, `OpenAIImageAgent`, and uses a `tmp_path` fixture pattern):

```python
def test_estimate_cost_returns_fixed_constant(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.estimate_cost() == 0.04
    assert agent.estimate_cost() == OpenAIImageAgent.ESTIMATED_COST_USD
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_planning_agent.py tests/agents/test_storyboard_agent.py tests/agents/test_prompt_agent.py tests/agents/test_image_agent.py tests/agents/test_openai_planning_agent.py tests/agents/test_openai_storyboard_agent.py tests/agents/test_openai_prompt_agent.py tests/agents/test_openai_image_agent.py -v`

Expected: the 8 new tests FAIL with `AttributeError: '<ClassName>' object has no attribute 'estimate_cost'`. All pre-existing tests in these files still PASS.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `src/video_draft_pipeline/agents/protocols.py` with:

```python
from typing import Protocol, runtime_checkable

from ..schema import Candidate, Narrative, ProjectInput, Prompts, Scene


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
```

In `src/video_draft_pipeline/agents/planning_agent.py`, add a method to the end of the `PlanningAgent` class (after `run`):

```python
    def estimate_cost(self) -> float:
        return 0.0
```

In `src/video_draft_pipeline/agents/storyboard_agent.py`, add a method to the end of the `StoryboardAgent` class (after `run`):

```python
    def estimate_cost(self) -> float:
        return 0.0
```

In `src/video_draft_pipeline/agents/prompt_agent.py`, add a method to the end of the `PromptAgent` class (after `run`):

```python
    def estimate_cost(self) -> float:
        return 0.0
```

In `src/video_draft_pipeline/agents/image_agent.py`, add a method to the end of the `ImageAgent` class (after `run`):

```python
    def estimate_cost(self) -> float:
        return 0.0
```

In `src/video_draft_pipeline/agents/openai_planning_agent.py`, change:

```python
class OpenAIPlanningAgent(BaseOpenAIAgent):
    error_cls = PlanningAgentError

    def __init__(
```

to:

```python
class OpenAIPlanningAgent(BaseOpenAIAgent):
    error_cls = PlanningAgentError
    ESTIMATED_COST_USD = 0.01

    def __init__(
```

and add a method to the end of the class (after `run`):

```python

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

In `src/video_draft_pipeline/agents/openai_storyboard_agent.py`, change:

```python
class OpenAIStoryboardAgent(BaseOpenAIAgent):
    error_cls = StoryboardAgentError

    def __init__(
```

to:

```python
class OpenAIStoryboardAgent(BaseOpenAIAgent):
    error_cls = StoryboardAgentError
    ESTIMATED_COST_USD = 0.01

    def __init__(
```

and add a method to the end of the class (after `run`):

```python

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

In `src/video_draft_pipeline/agents/openai_prompt_agent.py`, change:

```python
class OpenAIPromptAgent(BaseOpenAIAgent):
    error_cls = PromptAgentError

    def __init__(
```

to:

```python
class OpenAIPromptAgent(BaseOpenAIAgent):
    error_cls = PromptAgentError
    ESTIMATED_COST_USD = 0.005

    def __init__(
```

and add a method to the end of the class (after `run`):

```python

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

In `src/video_draft_pipeline/agents/openai_image_agent.py`, change:

```python
class OpenAIImageAgent(BaseOpenAIAgent):
    error_cls = ImageAgentError
    IMAGE_SIZE = "1536x1024"
```

to:

```python
class OpenAIImageAgent(BaseOpenAIAgent):
    error_cls = ImageAgentError
    IMAGE_SIZE = "1536x1024"
    ESTIMATED_COST_USD = 0.04
```

and add a method to the end of the class (after `run`):

```python

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/ -v`

Expected: PASS (all tests in the `tests/agents/` directory, including the 8 new ones).

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/agents/protocols.py src/video_draft_pipeline/agents/planning_agent.py src/video_draft_pipeline/agents/storyboard_agent.py src/video_draft_pipeline/agents/prompt_agent.py src/video_draft_pipeline/agents/image_agent.py src/video_draft_pipeline/agents/openai_planning_agent.py src/video_draft_pipeline/agents/openai_storyboard_agent.py src/video_draft_pipeline/agents/openai_prompt_agent.py src/video_draft_pipeline/agents/openai_image_agent.py tests/agents/test_planning_agent.py tests/agents/test_storyboard_agent.py tests/agents/test_prompt_agent.py tests/agents/test_image_agent.py tests/agents/test_openai_planning_agent.py tests/agents/test_openai_storyboard_agent.py tests/agents/test_openai_prompt_agent.py tests/agents/test_openai_image_agent.py
git commit -m "feat: add estimate_cost() to all agent protocols and implementations"
```

---

### Task 2: Wire budget guards into `run_pipeline`

**Files:**
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `estimate_cost() -> float` on all 8 agent classes (Task 1) and the `budget_guard(current_cost_usd, additional_cost_usd, max_budget_usd) -> float` / `BudgetExceededError` already defined in `src/video_draft_pipeline/guards.py`.
- Produces: a `_charge(running_cost: float, cost: float, max_budget_usd: float) -> float` module-level helper in `orchestrator.py` (raises `PipelineError` on overspend). No new public interface — `run_pipeline`'s signature is unchanged.

- [ ] **Step 1: Write the failing tests**

First, update the 4 existing fake test-double classes already in `tests/test_orchestrator.py` so they don't crash once `run_pipeline` calls `.estimate_cost()` on them. Change:

```python
class FakePlanningAgent:
    def run(self, project_input):
        return Narrative(
            beats=[Beat(beat_id="setup", description="fake-planning-marker", tone="calm")]
        )
```

to:

```python
class FakePlanningAgent:
    def run(self, project_input):
        return Narrative(
            beats=[Beat(beat_id="setup", description="fake-planning-marker", tone="calm")]
        )

    def estimate_cost(self):
        return 0.0
```

Change:

```python
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
```

to:

```python
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

    def estimate_cost(self):
        return 0.0
```

Change:

```python
class FakePromptAgent:
    def run(self, scene):
        return Prompts(image_prompt="fake-prompt-marker", video_motion_prompt="fake-motion")
```

to:

```python
class FakePromptAgent:
    def run(self, scene):
        return Prompts(image_prompt="fake-prompt-marker", video_motion_prompt="fake-motion")

    def estimate_cost(self):
        return 0.0
```

Change:

```python
class FakeImageAgent:
    def run(self, prompts):
        return Candidate(
            candidate_id="fake_cand_injected",
            image_url="fake://url",
            generated_by="fake-image-model",
        )
```

to:

```python
class FakeImageAgent:
    def run(self, prompts):
        return Candidate(
            candidate_id="fake_cand_injected",
            image_url="fake://url",
            generated_by="fake-image-model",
        )

    def estimate_cost(self):
        return 0.0
```

Then append these 4 new "expensive fake" classes and tests to the end of `tests/test_orchestrator.py`:

```python
class ExpensivePlanningAgent:
    def __init__(self):
        self.run_called = False

    def run(self, project_input):
        self.run_called = True
        return Narrative(beats=[Beat(beat_id="setup", description="d", tone="calm")])

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_planning_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensivePlanningAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, planning_agent=expensive_agent)

    assert expensive_agent.run_called is False


class ExpensiveStoryboardAgent:
    def __init__(self):
        self.run_called = False

    def run(self, narrative, project_input):
        self.run_called = True
        return []

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_storyboard_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensiveStoryboardAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, storyboard_agent=expensive_agent)

    assert expensive_agent.run_called is False


class ExpensivePromptAgent:
    def __init__(self):
        self.run_called = False

    def run(self, scene):
        self.run_called = True
        return Prompts(image_prompt="p", video_motion_prompt="m")

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_prompt_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensivePromptAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, prompt_agent=expensive_agent)

    assert expensive_agent.run_called is False


class ExpensiveImageAgent:
    def __init__(self):
        self.run_called = False

    def run(self, prompts):
        self.run_called = True
        return Candidate(candidate_id="c", image_url="u", generated_by="m")

    def estimate_cost(self):
        return 100.0


def test_run_pipeline_blocks_image_agent_over_budget():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=10,
        brief="Halloween Event",
        max_budget_usd=1.0,
    )
    expensive_agent = ExpensiveImageAgent()

    with pytest.raises(PipelineError):
        run_pipeline(project_input, image_agent=expensive_agent)

    assert expensive_agent.run_called is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`

Expected: the 4 new `test_run_pipeline_blocks_*_over_budget` tests FAIL — `run_pipeline` doesn't call `.estimate_cost()` yet, so nothing blocks the expensive fakes and no `PipelineError` is raised (the test's `pytest.raises(PipelineError)` block fails to catch an exception; depending on scene/duration math the run may complete normally or fail for an unrelated reason — either way, not the expected `PipelineError` from a budget check). Every other test in the file still PASSES (the fake classes' `estimate_cost` additions are inert until `run_pipeline` calls them).

- [ ] **Step 3: Write the implementation**

In `src/video_draft_pipeline/orchestrator.py`, change the guards import from:

```python
from .guards import duration_guard, DurationExceededError, BudgetExceededError
```

to:

```python
from .guards import duration_guard, budget_guard, DurationExceededError, BudgetExceededError
```

Add this module-level helper function just before `def run_pipeline(`:

```python
def _charge(running_cost: float, cost: float, max_budget_usd: float) -> float:
    try:
        return budget_guard(running_cost, cost, max_budget_usd)
    except BudgetExceededError as exc:
        raise PipelineError(str(exc)) from exc
```

Then change the body of `run_pipeline` from:

```python
    narrative = planning_agent.run(project_input)
    project.narrative = narrative

    scenes = storyboard_agent.run(narrative, project_input)

    try:
        duration_guard(scenes, project_input.max_duration_sec)
    except DurationExceededError as exc:
        raise PipelineError(str(exc)) from exc

    running_cost = 0.0
    for scene in scenes:
        scene.prompts = prompt_agent.run(scene)

        max_attempts = scene.max_retries + 1
        for _ in range(max_attempts):
            candidate = image_agent.run(scene.prompts)
```

to:

```python
    running_cost = 0.0

    running_cost = _charge(running_cost, planning_agent.estimate_cost(), project_input.max_budget_usd)
    narrative = planning_agent.run(project_input)
    project.narrative = narrative

    running_cost = _charge(running_cost, storyboard_agent.estimate_cost(), project_input.max_budget_usd)
    scenes = storyboard_agent.run(narrative, project_input)

    try:
        duration_guard(scenes, project_input.max_duration_sec)
    except DurationExceededError as exc:
        raise PipelineError(str(exc)) from exc

    for scene in scenes:
        running_cost = _charge(running_cost, prompt_agent.estimate_cost(), project_input.max_budget_usd)
        scene.prompts = prompt_agent.run(scene)

        max_attempts = scene.max_retries + 1
        for _ in range(max_attempts):
            running_cost = _charge(running_cost, image_agent.estimate_cost(), project_input.max_budget_usd)
            candidate = image_agent.run(scene.prompts)
```

Everything after that (`candidate.consistency_review = ...` through the end of the function) is unchanged — in particular, the existing `render_agent.run(scene, running_cost, project_input.max_budget_usd)` call and its `try`/`except BudgetExceededError` block stay exactly as they are.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`

Expected: PASS (all tests in the file, including the 4 new budget-blocking tests).

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`

Expected: all tests pass, zero failures (previous total was 145; this plan adds 8 tests in Task 1 + 4 tests in Task 2, so expect 157 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: guard budget against all 4 real agent costs, not just render"
```

---

## Self-Review Notes

- **Spec coverage:** Protocol + agent `estimate_cost()` additions (stub → `0.0`, real → fixed constant) → Task 1. `_charge` helper, `running_cost` initialization moved earlier, 4 new guard call sites (planning/storyboard/prompt/image), image guard firing per retry attempt, existing render guard untouched → Task 2. Fake test-double updates required by the spec's own "Test-double updates required" section → Task 2 Step 1. New orchestrator guard tests (one per call site, asserting `.run()` was never called) → Task 2 Step 1. Non-goals (no live metering, no `ReviewAgent`/`DirectorAgent`/`VideoRenderAgent` changes, no new `Project`/`Scene` cost field, no per-input cost scaling) — no task touches any of these.
- **Placeholder scan:** No TBD/TODO; every step has complete, runnable code; the 8 mechanical agent-class edits in Task 1 are each written out in full rather than "repeat for the other 7."
- **Type consistency:** `estimate_cost(self) -> float` matches across all 4 Protocols (Task 1), all 8 concrete implementations (Task 1), and the `_charge(running_cost: float, cost: float, max_budget_usd: float) -> float` signature that consumes it (Task 2) — no naming drift (e.g. no `get_cost`/`cost_estimate` variants).
