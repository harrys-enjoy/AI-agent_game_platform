# Orchestrator agent wiring — design spec

## Context

Four of the pipeline's seven stages now have real OpenAI-backed implementations: `OpenAIPlanningAgent`, `OpenAIStoryboardAgent`, `OpenAIPromptAgent`, and `OpenAIImageAgent`. None of them are referenced anywhere in `orchestrator.py` — `run_pipeline()` still constructs and calls only the stub classes (`PlanningAgent`, `StoryboardAgent`, `PromptAgent`, `ImageAgent`), so the "real" agents built across the last several branches have no path into the actual pipeline yet.

The remaining three stages (`ReviewAgent`, `DirectorAgent`, `VideoRenderAgent`, and its `VeoBackend`) are still stubs with no real implementation at all — there is nothing to wire for them yet.

No real OpenAI API key is available in this environment. `tests/test_orchestrator.py` currently runs `run_pipeline()` fully offline and deterministically, with zero mocking, because every agent it touches is a stub. Any wiring mechanism must preserve that: the 6 existing tests must keep passing unmodified, with `run_pipeline()` defaulting to stub behavior when nothing is specified.

This project (#64) is intended to eventually act as a single black-box sub-agent inside a larger, separate orchestrator system, invoked via one entry point rather than by reaching in and calling its internal agents directly. That's out of scope for this spec, but it's part of why the design below treats `run_pipeline()` itself as the one boundary worth keeping clean, rather than exposing per-agent wiring as a "public API."

## Goals

- Give `run_pipeline()` a way to use the 4 real agents instead of their stubs, per agent, per call.
- Preserve fully-offline default behavior: no config, no key, no network calls unless the caller explicitly opts in by passing a real agent instance.
- Keep all 6 existing `test_orchestrator.py` tests passing without modification.

## Non-goals

- Building real implementations for `ReviewAgent`, `DirectorAgent`, `VideoRenderAgent`, or `VeoBackend`. They remain stubs.
- Any live-API integration test. No OpenAI key exists in this environment; testing real-agent injection uses lightweight fake doubles that satisfy the same `run()` shape, not actual `OpenAI*Agent` instances.
- A config-driven / env-var-driven "use real agents" switch. Selection is per-agent, per-call, via explicit parameters — the caller decides, `run_pipeline` doesn't infer intent from environment.
- Exposing agent wiring as part of some future external API for an outer orchestrator system. This spec only concerns `run_pipeline()`'s own parameter surface.

## Design

### Selection mechanism: per-agent injection parameters

`run_pipeline` already has a precedent for this: `render_backend: RenderBackend | None = None`, defaulting to a stub-ish `VeoBackend` when not given. The same pattern extends naturally to the 4 ready agents — one optional parameter each, defaulting to `None`, falling back to the existing stub construction when not provided.

This was chosen over a single all-or-nothing switch because there's no API key yet: real agents will get turned on incrementally as keys/budget become available, not all at once. It also avoids adding any construction/config-resolution logic inside `run_pipeline` for how to build a real agent (model name, API key, output dir for the image agent) — that responsibility stays with the caller, exactly as it already does for `render_backend`.

### Typing: per-agent Protocols

None of the `OpenAI*Agent` classes inherit from their stub counterparts, so typing the new parameters against the concrete stub classes (e.g. `PlanningAgent | None`) would be structurally wrong for a caller passing in an `OpenAIPlanningAgent`. The codebase already solves this exact problem for `render_backend` via `RenderBackend`, a `Protocol` in `render_backends/base.py`. This spec adds the same treatment for the 4 agents.

**New file: `src/video_draft_pipeline/agents/protocols.py`**

```python
from typing import Protocol

from ..schema import Candidate, Narrative, ProjectInput, Prompts, Scene


class PlanningAgentProtocol(Protocol):
    def run(self, project_input: ProjectInput) -> Narrative: ...


class StoryboardAgentProtocol(Protocol):
    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]: ...


class PromptAgentProtocol(Protocol):
    def run(self, scene: Scene) -> Prompts: ...


class ImageAgentProtocol(Protocol):
    def run(self, prompts: Prompts) -> Candidate: ...
```

Each stub and each real agent already implements the matching `run()` signature (verified: all 4 `OpenAI*Agent` classes were built as drop-in replacements for their stubs, same params, same return types), so both satisfy these protocols structurally with no changes to the agent classes themselves.

### `orchestrator.py` changes

Add 4 new optional parameters to `run_pipeline`, typed against the new protocols, following the exact `render_backend` pattern:

```python
from .agents.protocols import (
    ImageAgentProtocol,
    PlanningAgentProtocol,
    PromptAgentProtocol,
    StoryboardAgentProtocol,
)


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

    # rest of the function body is unchanged
```

No changes to control flow, the retry loop, guards, or cost tracking. `review_agent` and `director_agent` construction stays as-is — those stages have no real implementation to inject yet.

### Testing

- All 6 existing `test_orchestrator.py` tests pass unmodified (defaults remain stub, so offline/deterministic behavior is unchanged).
- New tests: for each of the 4 new parameters, inject a minimal fake double (a small class or `unittest.mock.Mock` matching the protocol's `run()` signature) and assert it was called instead of the corresponding stub class — mirroring the existing `test_run_pipeline_explicit_backend_overrides_model_config` test's pattern for `render_backend`.
- No integration test against real `OpenAI*Agent` classes or the real OpenAI API — none of the specs in this project have live-API tests, and no key is available in this environment.

## Open questions / follow-ups (not blocking this spec)

- Once `ReviewAgent`/`DirectorAgent`/`VideoRenderAgent` get real implementations, they should follow the same injection pattern established here — no new mechanism should be needed.
- `docs/superpowers/specs/2026-07-29-openai-image-agent-design.md` flagged whether `media/` output images should be gitignored/cleaned up as worth resolving once the image agent is actually wired in. Now that this spec wires it in (as an opt-in path, still off by default), that decision is still open but slightly closer to mattering in practice; not addressed here since it's independent of the wiring mechanism itself.
