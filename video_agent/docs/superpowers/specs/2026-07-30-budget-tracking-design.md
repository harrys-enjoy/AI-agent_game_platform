# Budget tracking for real agent calls — design spec

## Context

The orchestrator-agent-wiring branch (`docs/superpowers/specs/2026-07-30-orchestrator-agent-wiring-design.md`) let `run_pipeline()` optionally use real `OpenAI*Agent` implementations for Planning/Storyboard/Prompt/Image, defaulting to stubs. Its final review flagged a gap it deliberately left unfixed as out of scope: `running_cost`/`budget_guard` in `orchestrator.py` only ever track render cost. None of the 4 real agents report a cost, so injecting any of them — most visibly `OpenAIImageAgent`, whose retry loop can fire up to `scene.max_retries + 1` real `images.generate()` calls per scene — spends real money while `max_budget_usd` reports as respected the entire time.

This spec closes that gap for all 4 real agents (not just image generation) — chat-completion calls also cost real money per call when a real API key is used, just usually less per call than image generation. The retry-loop amplification and reviewer's specific flag were about image cost being the largest and most repeated, but the underlying missing guard is identical for all 4.

## Goals

- Every one of the 4 real agents (`OpenAIPlanningAgent`, `OpenAIStoryboardAgent`, `OpenAIPromptAgent`, `OpenAIImageAgent`) reports an estimated per-call cost.
- `run_pipeline()` checks `budget_guard` against that estimate before calling any of the 4 agents, exactly the way it already guards before calling the render backend — a call that would blow the budget never happens.
- Stub agents remain free (`$0.00`), so default (no real agent injected) pipeline behavior is byte-identical to today — every existing test keeps passing without behavioral change.

## Non-goals

- Real, metered cost tracking (actual token counts, actual OpenAI billing API, actual per-image pricing tiers). This project has no live OpenAI key anywhere in its test/dev environment, and every other spec in this codebase already treats cost as a flat estimate (see `render_backends/veo_backend.py`'s `PRICE_PER_SEC_USD` table) — this spec follows the same convention, not a new one.
- Cost tracking for `ReviewAgent`, `DirectorAgent`, or `VideoRenderAgent`'s backend beyond what already exists (`VeoBackend.estimate_cost` is untouched). `ReviewAgent`/`DirectorAgent` are still stubs with no real implementation to cost-track.
- Exposing an aggregate cost field on `Project` or `Scene`. Today's render cost is only inspectable via `scene.render.cost_usd` per scene (callers `sum()` it themselves, see `tests/test_orchestrator.py`); this spec doesn't change that convention for the new cost sources either.
- Scaling cost by prompt length, image size, or any other call-specific input. Every estimate is a fixed flat number per agent, matching the "just a demo, not a metering system" simplicity already established across this project's specs.

## Design

### Protocol + agent changes

Each of the 4 `Protocol`s in `src/video_draft_pipeline/agents/protocols.py` gains one method:

```python
@runtime_checkable
class PlanningAgentProtocol(Protocol):
    def run(self, project_input: ProjectInput) -> Narrative: ...
    def estimate_cost(self) -> float: ...
```

(and the equivalent addition to `StoryboardAgentProtocol`, `PromptAgentProtocol`, `ImageAgentProtocol`).

**Stub agents** (`agents/planning_agent.py`, `storyboard_agent.py`, `prompt_agent.py`, `image_agent.py`) each get:

```python
def estimate_cost(self) -> float:
    return 0.0
```

**Real agents** each get a fixed class constant and a matching method:

```python
class OpenAIPlanningAgent(BaseOpenAIAgent):
    error_cls = PlanningAgentError
    ESTIMATED_COST_USD = 0.01

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

Values used: `OpenAIPlanningAgent.ESTIMATED_COST_USD = 0.01`, `OpenAIStoryboardAgent.ESTIMATED_COST_USD = 0.01`, `OpenAIPromptAgent.ESTIMATED_COST_USD = 0.005`, `OpenAIImageAgent.ESTIMATED_COST_USD = 0.04`. These are illustrative flat per-call estimates (chat completions cheap, image generation the expensive one), the same spirit as `OpenAIImageAgent.IMAGE_SIZE` already being a fixed constant and `VeoBackend`'s flat `$/sec` table — not live metering.

### Orchestrator changes

`src/video_draft_pipeline/orchestrator.py`:

1. `running_cost = 0.0` moves from its current position (right before the per-scene loop) to the top of `run_pipeline`, before the planning-agent call — planning and storyboard now need guarding too, and both run before the loop.
2. A small local helper avoids repeating the same try/except at every new call site:

```python
def _charge(running_cost: float, cost: float, max_budget_usd: float) -> float:
    try:
        return budget_guard(running_cost, cost, max_budget_usd)
    except BudgetExceededError as exc:
        raise PipelineError(str(exc)) from exc
```

3. Four new guard-then-call points:

```python
running_cost = _charge(running_cost, planning_agent.estimate_cost(), project_input.max_budget_usd)
narrative = planning_agent.run(project_input)
project.narrative = narrative

running_cost = _charge(running_cost, storyboard_agent.estimate_cost(), project_input.max_budget_usd)
scenes = storyboard_agent.run(narrative, project_input)

# ... duration_guard unchanged ...

for scene in scenes:
    running_cost = _charge(running_cost, prompt_agent.estimate_cost(), project_input.max_budget_usd)
    scene.prompts = prompt_agent.run(scene)

    max_attempts = scene.max_retries + 1
    for _ in range(max_attempts):
        running_cost = _charge(running_cost, image_agent.estimate_cost(), project_input.max_budget_usd)
        candidate = image_agent.run(scene.prompts)
        # ... review/director/append unchanged ...
```

The image-agent guard runs fresh on every retry attempt, so a scene whose retries would blow the budget stops the whole pipeline immediately with `PipelineError` rather than continuing to spend — consistent with the existing render guard already treating "over budget" as a hard stop for the entire pipeline, not a per-scene skip. The existing render call site and its guard are untouched.

Since stub `estimate_cost()` always returns `0.0`, `running_cost` stays exactly `0.0` through all 4 new guard checks whenever nothing real is injected. Default (all-stub) pipeline behavior is unchanged.

### Test-double updates required (from the prior branch)

`tests/test_orchestrator.py` already contains fake test-double classes from the orchestrator-agent-wiring plan (`FakePlanningAgent`, `FakeStoryboardAgent`, `FakePromptAgent`, `FakeImageAgent`). Once `run_pipeline` unconditionally calls `.estimate_cost()` on whatever it's given, these fakes need `estimate_cost(self) -> float: return 0.0` added, or their existing tests break with `AttributeError`. This is a required update to already-shipped test code, not new coverage — noting it explicitly so it isn't a surprise mid-implementation.

## Testing

- **Stub agents** (4 tests, one per existing stub test file): `estimate_cost()` returns `0.0`.
- **Real agents** (4 tests, one per existing `OpenAI*Agent` test file): `estimate_cost()` returns the documented fixed constant. No client/network involvement.
- **Existing fake doubles updated** (`test_orchestrator.py`): each gets `estimate_cost() -> 0.0` added so their pre-existing tests keep passing unmodified in behavior.
- **New orchestrator guard tests** (4 tests, one per new guard call site): inject a fake or real (mocked-client) agent whose `estimate_cost()` returns a deliberately large number, paired with a small `max_budget_usd`, and assert `run_pipeline` raises `PipelineError` before `.run()` is ever called on that agent (assert via a call-tracking flag on the fake, or `Mock.assert_not_called()` for the real-agent-with-mocked-client variant).
- No live-API integration test, consistent with every other spec in this project.

## Open questions / follow-ups (not blocking this spec)

- The flat per-call cost constants are placeholders. If real OpenAI pricing data becomes available (once a live key exists in this environment), they should be revisited — not urgent, since this project has no live-API testing anywhere yet.
- `media/` gitignore and the agent-construction ergonomics gap (flagged in the orchestrator-agent-wiring branch's final review, Minor-4 and Recommendation-2) remain open and are unrelated to this spec.
