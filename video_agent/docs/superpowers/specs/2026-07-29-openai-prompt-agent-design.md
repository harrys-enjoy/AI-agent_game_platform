# Design: OpenAIPromptAgent (real implementation)

## Context

`PlanningAgent` and `StoryboardAgent` now have real implementations (see the two prior specs in this directory). This spec covers the third pipeline stage, `PromptAgent`: `.run(scene: Scene) -> Prompts`, called once per scene (`orchestrator.py:50`) to turn a scene's storyboard (camera/subject/action/setting/required_elements) into `Prompts` (`image_prompt`, `video_motion_prompt`) for `ImageAgent`.

Unlike `Scene` (which mixes creative fields with numeric/structural ones) or `Narrative` (a flat, unconstrained shape), `Prompts` is the simplest output type yet: two plain `str` fields, no numeric or business-rule constraints. This means the design lessons learned from the prior two agents apply differently here — see Architecture.

Model keys are still not available. Same as before: build and merge now, verify live once a key exists.

## Goals

- Implement a real `OpenAIPromptAgent` producing `Prompts` from a `Scene`, matching the stub `PromptAgent`'s `.run(scene) -> Prompts` interface exactly so the two remain interchangeable.
- When `scene.storyboard.required_elements` is non-empty, guarantee it appears in `image_prompt` — deterministically, in Python, after the model responds. Never trust the model to remember a compliance requirement, the same rule applied to `StoryboardAgent`'s brand placement.
- Fail loud on any malformed model response (refusal) or SDK failure, both as a single `PromptAgentError`.
- Leave the existing stub `PromptAgent` and its 2 tests completely untouched.

## Non-goals

- Orchestrator wiring (same deferral as the prior two specs).
- Automated live-API test coverage — no key yet.
- Any other agent (`ImageAgent`, `ReviewAgent`, `DirectorAgent`).
- Extracting shared plumbing across the three real agents (key resolution, client injection). This is the third real agent, and a prior review flagged this as the natural point to extract — explicitly deferred anyway, as its own follow-up refactor with its own spec, not smuggled into this feature spec.
- Changing the orchestrator's retry loop to re-invoke `PromptAgent` with director feedback on a "regenerate" decision. Currently `PromptAgent.run()` is called once per scene, before the retry loop (`orchestrator.py:50`), and the loop only re-runs image/review/director on the same prompts. This spec does not change that behavior — noted here only so it isn't mistaken for an oversight; it's existing pipeline architecture, out of scope for a single-agent spec.

## Architecture

New file: `src/video_draft_pipeline/agents/openai_prompt_agent.py`

```python
from openai import OpenAI

from .. import config
from ..schema import Prompts, Scene
from .openai_planning_agent import MissingAPIKeyError


class PromptAgentError(Exception):
    pass


def _build_messages(scene: Scene) -> list[dict]:
    ...


class OpenAIPromptAgent:
    def __init__(
        self,
        model_name: str = "gpt-5-mini",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        ...

    def run(self, scene: Scene) -> Prompts:
        ...
```

`MissingAPIKeyError` is imported from `openai_planning_agent.py`, not redefined — same as `OpenAIStoryboardAgent`.

### Key resolution

Identical to both prior real agents: explicit `api_key` arg → `config.load_api_keys().openai_api_key` → `MissingAPIKeyError` if neither resolves.

### Structured output — no draft type needed

`Prompts` is used **directly** as `response_format`, the same way `OpenAIPlanningAgent` uses `Narrative` directly. This is a deliberate contrast with `OpenAIStoryboardAgent`, which needed a throwaway `SceneDraft`/`StoryboardDraft` type specifically because `Scene` carries fields (`duration_sec`, `scene_id`, `order`) that must satisfy exact numeric/business constraints the model can't be trusted with. `Prompts` has no such fields — both `image_prompt` and `video_motion_prompt` are freeform strings with no constraint to violate, so there's nothing for a draft type to protect against. (This also sidesteps the exact class of bug found in `OpenAIStoryboardAgent`'s final review: a `Field(gt=0)`-style constraint on a `response_format` field can make OpenAI's strict schema reject the request outright. `Prompts` has no constrained fields, so this risk doesn't arise here — but if a future agent's output type ever needs one, enforce it in Python after the response, not as a Pydantic constraint on the wire model, per that lesson.)

Prompt content (`_build_messages`): a system message asking for an `image_prompt` and a `video_motion_prompt` derived from a scene's camera/subject/action/setting, instructing Korean-language output per the project's convention. A user message built from `scene.storyboard.camera/subject/action/setting`. Exact wording is an implementation detail.

### Required-elements enforcement (post-processing, not validation)

After a successful, non-refused response:

```python
image_prompt = parsed.image_prompt
if scene.storyboard.required_elements:
    image_prompt = f"{image_prompt}, {', '.join(scene.storyboard.required_elements)}"
return Prompts(image_prompt=image_prompt, video_motion_prompt=parsed.video_motion_prompt)
```

Only `image_prompt` gets the append — `required_elements` are on-screen visual content (e.g. a logo), which is an image concern; `video_motion_prompt` stays camera-movement-only, matching the stub's existing separation of concerns. This is different in kind from `StoryboardAgent`'s validation (which rejected bad model output); here the model's output is always accepted as-is and Python *adds* the guaranteed content afterward — there's nothing to reject, since a model that already mentioned the required elements just gets them appended again (redundant text, not a correctness problem for an image-generation prompt).

### Error handling

Two failure modes only, both becoming `PromptAgentError`: an SDK exception (auth/network/etc., wrapped) or a refusal (`message.parsed is None`, checked explicitly — same as both prior agents). No count/alignment validation surface exists here, unlike `StoryboardAgent` — there's exactly one object being generated, not a list that has to line up against anything else.

## Data flow

No change to the pipeline's shape. `OpenAIPromptAgent` and the stub `PromptAgent` are interchangeable at whatever call site constructs `prompt_agent` — both take a `Scene` and return `Prompts`.

## Dependencies

None new — `openai` is already a runtime dependency.

## Testing

No live-API test (see Non-goals). Key-free unit tests, mocking only the SDK client boundary:

- Fail-fast construction with no key (reusing the already-tested `MissingAPIKeyError`).
- `_build_messages` shape.
- A full successful `run()` where `required_elements` is non-empty: verify `image_prompt` contains both the model's own content and the appended required elements, and `video_motion_prompt` is unmodified from the model's response.
- A full successful `run()` where `required_elements` is empty: verify `image_prompt` is exactly the model's response, unmodified (no trailing comma or empty append artifact).
- Refusal (`parsed is None`) → `PromptAgentError`.
- Generic SDK exception → `PromptAgentError`.

The existing 92 tests must continue to pass unchanged.

## Open questions for follow-up (not blocking this spec)

- Extracting shared plumbing (key resolution, client injection, possibly a common base class) across all three real agents — explicitly deferred per Non-goals, now genuinely due as its own follow-up task.
- Whether the orchestrator's retry loop should eventually re-invoke `PromptAgent` with director feedback to refine prompts on a "regenerate" decision, instead of retrying image generation against unchanged prompts — a real product question, but an orchestrator-level one, out of scope here.
- `ImageAgent`'s real implementation is a different shape entirely (image generation, not text) — likely the first agent in this project that isn't a plain OpenAI chat completion, and probably needs its own exploration of what "real" even means without a rendering budget.
