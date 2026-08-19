# Design: OpenAIStoryboardAgent (real implementation)

## Context

`PlanningAgent` now has a real implementation (`OpenAIPlanningAgent`, see `docs/superpowers/specs/2026-07-28-openai-planning-agent-design.md`), the second pipeline stage. This spec covers the next stage, `StoryboardAgent`, which turns a `Narrative` (4 beats) plus the original `ProjectInput` into a `list[Scene]` — one scene per beat, each with camera/subject/action/setting/required-elements and a duration in seconds that must sum exactly to `project_input.duration_sec`.

Unlike `Narrative`, a `Scene` mixes model-appropriate creative fields (`storyboard.camera/subject/action/setting/required_elements`) with pipeline-computed structural fields (`scene_id`, `order`, `duration_sec`) that a language model cannot be trusted to produce reliably — Structured Outputs cannot enforce a numeric constraint like "these durations sum to exactly N." This is the main way this agent's design differs from `OpenAIPlanningAgent`.

Model keys are still not available. Same as before: build and merge now, verify live once a key exists.

## Goals

- Implement a real `OpenAIStoryboardAgent` that produces a `list[Scene]` from a `Narrative` + `ProjectInput`, matching the stub `StoryboardAgent`'s `.run(narrative, project_input) -> list[Scene]` interface exactly so the two remain interchangeable.
- Dynamic, model-driven scene pacing: instead of an even time split (the stub's behavior), the model proposes a relative importance weight per beat, and Python converts those weights into exact seconds that still sum precisely to `project_input.duration_sec`.
- Keep all pipeline-structural fields (`scene_id`, `order`, `duration_sec`) and the brand-requirement placement rule deterministic in Python — never trust the model with a value that has to satisfy an exact numeric or business-rule constraint.
- Fail loud and specific on any malformed model response (wrong scene count, mismatched/reordered beats, refusal), not just on outright API failure.
- Leave the existing stub `StoryboardAgent` and its 6 tests completely untouched.

## Non-goals

- Orchestrator wiring (same deferral as the planning agent spec).
- Automated live-API test coverage — no key yet; deferred to a future key-gated smoke test.
- Any other agent (`PromptAgent`, `ImageAgent`, `ReviewAgent`, `DirectorAgent`).
- Extracting shared plumbing between `OpenAIPlanningAgent` and `OpenAIStoryboardAgent` (e.g. a common base class for key resolution). Two real agents is not enough evidence for the right abstraction; revisit after a third.

## Architecture

New file: `src/video_draft_pipeline/agents/openai_storyboard_agent.py`

```python
from openai import OpenAI
from pydantic import BaseModel, Field

from .. import config
from ..schema import BeatId, Narrative, ProjectInput, Scene, Storyboard
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
    duration_weight: float


class StoryboardDraft(BaseModel):
    scenes: list[SceneDraft]


def _build_messages(narrative: Narrative, project_input: ProjectInput) -> list[dict]:
    ...


def _drafts_to_scenes(
    drafts: list[SceneDraft], project_input: ProjectInput
) -> list[Scene]:
    ...


class OpenAIStoryboardAgent:
    def __init__(
        self,
        model_name: str = "gpt-5.4",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        ...

    def run(self, narrative: Narrative, project_input: ProjectInput) -> list[Scene]:
        ...
```

`MissingAPIKeyError` is imported from `openai_planning_agent.py`, not redefined — same failure mode, one definition. `StoryboardAgentError` is new and local, mirroring `PlanningAgentError`.

### Key resolution

Identical to `OpenAIPlanningAgent`: explicit `api_key` arg → `config.load_api_keys().openai_api_key` → `MissingAPIKeyError` if neither resolves. Same fail-fast-at-construction behavior.

### Structured output and the draft shape

`SceneDraft`/`StoryboardDraft` exist only as the OpenAI response contract — they are constructed by `client.chat.completions.parse(response_format=StoryboardDraft)`, converted into real `Scene` objects within `run()`, and discarded. They are never imported or referenced outside this file, and are not added to `schema.py`: `schema.py` holds the pipeline's real domain data; these are one agent's private, throwaway API contract.

Prompt content (`_build_messages`): a system message instructing the model to produce one scene per beat (camera/subject/action/setting/required_elements/duration_weight), each tied to a `beat_id`, and — per the project's Korean-language convention — to respond in Korean, matching the existing stub's Korean strings. A user message built from the narrative's beats plus `project_input.preset/scene_type/brief`. Exact wording is an implementation detail.

### Validation

After a successful parse, before conversion:

1. **Refusal check** — same as `OpenAIPlanningAgent`: if `message.parsed is None`, raise `StoryboardAgentError` with the refusal reason.
2. **Alignment check** — `[d.beat_id for d in draft.scenes] == [b.beat_id for b in narrative.beats]`. A single ordered-list comparison catches both a wrong scene count and a reordered/mismatched response in one check; raise `StoryboardAgentError` naming the mismatch if it fails.
3. **`duration_weight > 0`** is enforced explicitly in Python, after the alignment check and before conversion: `if any(scene.duration_weight <= 0 for scene in draft.scenes): raise StoryboardAgentError(...)`. This is **not** a Pydantic `Field(gt=0)` constraint on `SceneDraft` — an earlier version of this spec proposed that, but it was found to be actively harmful: OpenAI's Structured Outputs strict JSON schema subset does not support numeric-range keywords (`exclusiveMinimum`, etc.), so a `Field(gt=0)` on a field sent as `response_format` makes the SDK emit an unsupported keyword and the **API itself rejects the request with a 400 on every call**. The lesson generalizes: Pydantic constraints are safe on fields that are only ever constructed locally (like `Scene`), but any constraint on a field that becomes part of a `response_format` schema must be verified against OpenAI's supported strict-schema keyword subset first — plain, unconstrained types are the safe default for response-format models, with validation done in Python afterward instead.

### Deterministic conversion (`_drafts_to_scenes`)

For each aligned `(beat, draft)` pair, in order:
- `scene_id = f"scene_{i+1:02d}"`, `order = i+1` — same scheme as the stub.
- `duration_sec`: computed from `draft.duration_weight` relative to the sum of all weights, scaled against `project_input.duration_sec`, with the **last** scene absorbing the exact float remainder (`duration_sec - sum(the others)`) rather than being computed from its own weight — the same remainder trick the stub already uses, guaranteeing an exact sum despite floating point.
- `storyboard = Storyboard(camera=draft.camera, subject=draft.subject, action=draft.action, setting=draft.setting, required_elements=[...])` — `required_elements` is **force-set** here, not taken from the draft: `project_input.brand_requirements` if `beat.beat_id == "resolution"`, else `[]`. This is the hard Python rule from Decision 2 — the model's own `required_elements` output is discarded, not merged.

### Error handling

Same one-exception-type philosophy as `OpenAIPlanningAgent`: any SDK-level failure (auth, network, refusal) or validation failure (misalignment) becomes `StoryboardAgentError`. Callers handle one exception type, not `openai`'s hierarchy plus a separate validation-error type.

## Data flow

No change to the pipeline's shape. `OpenAIStoryboardAgent` and the stub `StoryboardAgent` are interchangeable at whatever call site constructs `storyboard_agent` — both take `(narrative, project_input)` and return `list[Scene]`.

## Dependencies

None new — `openai` is already a runtime dependency (added for `OpenAIPlanningAgent`).

## Testing

No live-API test (see Non-goals). Key-free unit tests, mocking only the SDK client boundary, covering:

- Fail-fast construction with no key (reusing the already-tested `MissingAPIKeyError` behavior — this test confirms `OpenAIStoryboardAgent` wires it correctly, not that the exception itself works).
- `_build_messages` shape.
- A full successful `run()`: verifies computed durations sum exactly to `project_input.duration_sec`, verifies the weighting actually produces different durations for different weights (not just an even split), and verifies `required_elements` lands only on the resolution scene regardless of what the mocked draft contained there.
- Scene-count/beat-order mismatch → `StoryboardAgentError`.
- Refusal (`parsed is None`) → `StoryboardAgentError`.
- Generic SDK exception → `StoryboardAgentError`.
- Non-positive `duration_weight` in the response → `StoryboardAgentError` (added post-implementation; see Addendum below).
- A `ValidationError` from `_drafts_to_scenes` (e.g. a computed duration rounding to `<= 0` on extreme weight ratios) → wrapped as `StoryboardAgentError`, not left to escape raw (added post-implementation).
- Empty-beat `Narrative` → `StoryboardAgentError`, matching the stub's `ValueError` for the same input (added post-implementation).

The existing 71 tests must continue to pass unchanged.

## Addendum: findings from the final whole-branch review

Three issues were found during final review, after all 4 implementation tasks had already passed their individual task reviews — each was invisible to a single task's diff because it only became visible from the whole file, or from reasoning about the live API contract that no offline test exercises. All three were fixed in a follow-up commit; this doc has been updated in place to reflect the shipped design (see `Field(gt=0)` removal above), but the story is worth keeping for the next agent's design:

1. **`Field(gt=0)` on a `response_format` field is unsafe, not just untestable.** The original Validation section (above) claimed this constraint was "enforced by Pydantic at parse time" and treated it as a minor testability gap. That was wrong in a more serious way: OpenAI's strict Structured Outputs schema subset does not support numeric-range keywords at all, so declaring `Field(gt=0)` on a field sent as `response_format` makes the SDK emit an unsupported `exclusiveMinimum` keyword, and the **API rejects the entire request** — not a validation nuance, a total live-call failure. Fixed by making `duration_weight` a plain `float` and validating positivity explicitly in Python after the response comes back.
2. **Structural validation must happen inside the same error boundary as everything else.** `_drafts_to_scenes` was originally called after (outside) the try/except wrapping the SDK call, so a `ValidationError` it raised (from Python's own downstream `Scene(duration_sec=...)` constraint) could escape `run()` unwrapped, contradicting the "callers only handle one exception type" goal. Fixed by wrapping that call in its own try/except.
3. **"Matches the stub's interface" must include matching its failure modes, not just its happy path.** The stub raises on an empty beat list; the real agent originally didn't, silently returning an empty scene list instead. Fixed with an explicit guard at the top of `run()`.

## Open questions for follow-up (not blocking this spec)

- Whether `PromptAgent`'s real implementation needs a similar draft/validation split, or whether its output (`Prompts`: `image_prompt`, `video_motion_prompt`) is simple enough to use Structured Outputs directly against the real schema type, like `OpenAIPlanningAgent` does.
- Whether to extract a shared `_load_api_key(...)` helper once a third real agent exists (deferred per Non-goals).
- The render-backend video-stitching gap discussed separately (mixed-backend clips needing a normalized spec before `assembly.py`'s ffmpeg concat) — unrelated to this agent, tracked separately.
