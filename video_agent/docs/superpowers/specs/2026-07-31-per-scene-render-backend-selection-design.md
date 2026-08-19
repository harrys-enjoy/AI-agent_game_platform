# Per-scene render backend selection — design spec

## Context

The pipeline's render stage currently uses exactly one `RenderBackend` for every scene in a project — whichever instance is injected via `run_pipeline`'s `render_backend` param (or the `StubRenderBackend` default). `schema.RenderBackendName` and the `render_backends/` module already anticipate more than one real backend existing side by side: `VeoBackend` (real, this session) and `SelfHostedBackend` (still a stub, intended to eventually be a free self-hosted video-diffusion model, per earlier conversation — not designed here). The user's stated goal is to mix them within a single video: spend on the paid, higher-quality backend (Veo) only for the beats that matter most, and use the free backend for the rest.

This spec covers **only the selection mechanism** — deciding which backend a given scene routes to, and threading that choice through `VideoRenderAgent`/`run_pipeline`. `SelfHostedBackend`'s own real implementation is explicitly out of scope (its target model/API isn't chosen yet) and follow-up work: the mechanism designed here works against any two `RenderBackend`-conforming instances, real or stub, so it doesn't block on that decision.

## Goals

- `VideoRenderAgent` can route a scene to a different backend based on `scene.beat_id`, while staying fully backward compatible with today's single-backend usage.
- The default split: `climax`/`resolution` (the highest-value beats) → the paid/high-quality backend; `setup`/`conflict` → the free backend. A small helper encodes this specific mapping for convenience, but the underlying mechanism accepts an arbitrary beat→backend map, so other splits remain possible without further code changes.
- `run_pipeline` exposes the new mapping as an optional injection parameter, following the same pattern as every other stage's injection.
- Cost estimation and the actual render always agree on which backend was used for a given scene — no drift between what the budget guard charged and what actually ran.

## Non-goals

- `SelfHostedBackend`'s real implementation (model choice, API shape) — separate future spec, blocked on the user deciding what to actually run.
- Any changes to the `RenderBackend` protocol itself (`name`, `render(candidate, motion_prompt, duration_sec)`, `estimate_cost(duration_sec)`) — no existing backend class (`VeoBackend`, `StubRenderBackend`, `SelfHostedBackend`) needs to change.
- Budget-driven or other dynamic selection criteria (e.g. falling back to the free backend once budget gets tight) — beat-type is the only criterion this spec implements; other criteria are a possible future direction, not designed here.
- `build_real_agents()`/`agents/factory.py` changes — the render stage has never been part of that factory (it's injected separately via `run_pipeline`'s own `render_backend` param), and this spec doesn't change that.
- The LTX 2.3 model mentioned as a possible future cheap option — unevaluated, unrelated to this spec.

## Design

### `VideoRenderAgent` — selection logic

`VideoRenderAgent` gains an optional `backend_by_beat` param. `backend` stays required and now doubles as the fallback for any beat not present in the map:

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
```

`_estimate_cost` (the old standalone method) is folded into `run()` directly since it now needs the same `_select_backend(scene)` call `render()` uses — keeping them as two separate methods risked them silently selecting different backends if one were changed without the other. `backend_by_beat=None` (the default) makes `_select_backend` always return `backend`, identical to today's behavior — every existing caller that only ever passed `backend=` sees zero change.

### Convenience helper for the default split

```python
def beat_backend_map(paid_backend: RenderBackend, free_backend: RenderBackend) -> dict[BeatId, RenderBackend]:
    return {
        "climax": paid_backend,
        "resolution": paid_backend,
        "setup": free_backend,
        "conflict": free_backend,
    }
```

Lives in `agents/video_render_agent.py`, next to the class that consumes its output shape. Purely a convenience for the one split this spec locks in — `backend_by_beat` itself stays a plain arbitrary `dict[BeatId, RenderBackend]`, so a caller wanting a different split (e.g. climax-only) just builds their own dict; nothing routes through this helper by force.

### `run_pipeline` threading

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
    ...
    backend = render_backend or StubRenderBackend(tier=models.render_backend)
    render_agent = VideoRenderAgent(backend=backend, backend_by_beat=render_backend_by_beat)
    ...
```

One new, purely additive param. `BeatId` needs importing into `orchestrator.py` from `.schema` (already exported there) for the type hint. Nobody who doesn't pass `render_backend_by_beat` observes any behavior change — `render_backend`'s existing semantics (single backend, or the `StubRenderBackend` default) are untouched.

### Budget guard interaction

Already covered above: `_select_backend(scene)` runs once per `run()` call and feeds both the pre-charge `estimate_cost()` call and the actual `render()` call, so the existing budget-guard discipline (`current_cost_usd` checked before spending, `PipelineError` raised via the orchestrator's `_charge`/`BudgetExceededError` wrapping) holds exactly as it does today — just against whichever backend that scene's beat routes to.

## Testing

- `tests/agents/test_video_render_agent.py`: existing tests (constructed with only `backend=`) must keep passing completely unmodified — this is what proves the `backend_by_beat=None` fallback is a true no-op. New tests: a scene with `beat_id="climax"` (and one with `beat_id="setup"`) routes through a `backend_by_beat` map to the correct backend instance (distinguishable via a marker attribute on two fake backend doubles); a beat not present in a partial map falls back to `backend`; a cost/render consistency test proving the backend charged via `estimate_cost()` is the same instance whose `render()` actually ran (e.g. an expensive fake backend for `climax` with a cheap one as the fallback `backend`, asserting the budget guard used the expensive one's cost).
- New test for `beat_backend_map()`: asserts the exact 4-key mapping (`climax`/`resolution` → the paid instance, `setup`/`conflict` → the free instance).
- `tests/test_orchestrator.py`: a test injecting `render_backend_by_beat` built from two fake backends (matching the existing `FakeImageAgent`/`FakePromptAgent`-style test doubles already used in this file) into `run_pipeline`, asserting climax/resolution scenes render via one and setup/conflict scenes render via the other, across the pipeline's real default 4-beat storyboard.
- No live-API tests — the mechanism itself never talks to a real backend; whatever `RenderBackend`-conforming instances are injected (stub, fake test doubles, or eventually real `VeoBackend`/`SelfHostedBackend`) are the caller's concern, not this spec's.

## Open questions / follow-ups (not blocking this spec)

- `SelfHostedBackend`'s real implementation — once a model/API is chosen, wiring it into per-scene selection needs zero changes to anything designed here; it's just another `RenderBackend`-conforming instance passed into `beat_backend_map()` or a custom `backend_by_beat` dict.
- Whether selection criteria should ever expand beyond beat-type (e.g. budget-driven fallback, explicit per-scene override independent of beat) — not designed here, would need its own follow-up if it comes up.
- The exact beat→backend split (`climax`+`resolution` vs. `setup`+`conflict`) is a starting point the user chose, not something empirically validated — may need revisiting once real output from both backends exists to compare.
