# Design: OpenAIImageAgent (real implementation)

## Context

`PlanningAgent`, `StoryboardAgent`, and `PromptAgent` all now have real OpenAI-backed implementations, and a follow-up refactor (`docs/superpowers/specs/2026-07-29-openai-agent-shared-plumbing-design.md`) extracted their common plumbing into `BaseOpenAIAgent` (`src/video_draft_pipeline/agents/openai_agent_base.py`). This spec covers the fourth pipeline stage, `ImageAgent`: `.run(prompts: Prompts) -> Candidate`, called inside the orchestrator's per-scene retry loop (`orchestrator.py:59`, up to `scene.max_retries + 1` times) to turn a scene's `image_prompt` into a `Candidate` for `ReviewAgent`/`DirectorAgent` to judge.

This is the first real agent that isn't a plain chat completion. The prior prompt-agent spec's Open Questions flagged exactly this: `ImageAgent` needed its own exploration of what "real" means, since it calls a fundamentally different OpenAI endpoint (`images.generate`, not `chat.completions.parse`) with no `response_format`/structured-output mechanism at all.

The key design gap, resolved through this brainstorming session: `Candidate.image_url` is a required `str`, but OpenAI's image-generation API (confirmed against current `gpt-image-2` documentation, which returns `result.data[0].b64_json`) hands back base64-encoded image bytes, not a hosted URL. Resolution: decode the bytes and write them to a local file, returning the file's path as `image_url`. This project has no cloud storage/CDN and doesn't need one yet — this is a demo pipeline generating short marketing videos, not a hosted product.

Aspect ratio / image size is explicitly **not** configurable per project in this spec: nothing in `ProjectInput` or `Scene` carries a shape/aspect-ratio concept today, and since `ImageAgent` only produces a still frame consumed later by `VideoRenderAgent` (not the final video itself), a fixed default size is sufficient for a demo. Making size configurable would mean extending `ProjectInput`'s schema and threading it through `StoryboardAgent`/`PromptAgent` too — out of scope here (see Non-goals).

Model keys are still not available. Same as all three prior agents: build and merge now, verify live once a key exists.

## Goals

- Implement a real `OpenAIImageAgent` producing a `Candidate` from `Prompts`, matching the stub `ImageAgent`'s `.run(prompts) -> Candidate` interface exactly so the two remain interchangeable.
- Call OpenAI's real image-generation API (`client.images.generate`), decode the returned base64 image, and persist it to a local file, since `Candidate.image_url` requires a resolvable string and the API returns raw bytes, not a URL.
- Reuse `BaseOpenAIAgent` for constructor/key-resolution/client-injection, consistent with all three existing real agents — without stretching `_structured_completion` to cover a call shape it wasn't designed for (no `response_format`, no `.parsed`).
- Fail loud on any SDK failure or unusable response, as a single `ImageAgentError`.
- Leave the existing stub `ImageAgent` and its 2 tests completely untouched.

## Non-goals

- Orchestrator wiring (same deferral as all three prior specs).
- Automated live-API test coverage — no key yet.
- Per-project configurable aspect ratio / image size. Nothing in the schema carries this concept today; adding it would mean extending `ProjectInput` and threading it through `StoryboardAgent`/`PromptAgent`, not just `ImageAgent`. Noted as an explicit open question below, not an oversight.
- `image_edit_model` (`gemini-2.5-flash-image`, declared in `ModelConfig` but unused anywhere in the codebase). That's a different provider (Gemini, not OpenAI) with a different response shape (`interaction.output_image.data` via `client.interactions.create`), presumably for a future "regenerate with edits" flow. Out of scope for this spec, which only makes the OpenAI image-generation path real.
- Any other agent (`ReviewAgent`, `DirectorAgent`, `VideoRenderAgent`).
- Extending `BaseOpenAIAgent` with a shared image-generation helper. `ImageAgent` is the only consumer of the Images API today; adding shared plumbing for a hypothetical second caller (e.g. a future edit-based agent) is speculative. Extract only when a second real consumer exists.

## Architecture

New file: `src/video_draft_pipeline/agents/openai_image_agent.py`

```python
import base64
import uuid
from pathlib import Path

from openai import OpenAI

from ..schema import Candidate, Prompts
from .openai_agent_base import BaseOpenAIAgent


class ImageAgentError(Exception):
    pass


class OpenAIImageAgent(BaseOpenAIAgent):
    error_cls = ImageAgentError
    IMAGE_SIZE = "1536x1024"

    def __init__(
        self,
        model_name: str = "gpt-image-2",
        output_dir: str | Path = "media",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        super().__init__(model_name, api_key, client)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, prompts: Prompts) -> Candidate:
        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        try:
            response = self._client.images.generate(
                model=self.model_name,
                prompt=prompts.image_prompt,
                size=self.IMAGE_SIZE,
            )
        except Exception as exc:
            raise self.error_cls(f"OpenAI image call failed: {exc}") from exc

        if not response.data or response.data[0].b64_json is None:
            raise self.error_cls("OpenAI image call returned no image data")

        image_bytes = base64.b64decode(response.data[0].b64_json)
        file_path = self.output_dir / f"{candidate_id}.png"
        file_path.write_bytes(image_bytes)

        return Candidate(
            candidate_id=candidate_id,
            image_url=str(file_path),
            generated_by=self.model_name,
        )
```

`OpenAIImageAgent` subclasses `BaseOpenAIAgent` for the constructor only — `__init__` delegates key resolution and client injection exactly like the other three agents, inheriting `MissingAPIKeyError` behavior unchanged. `run()` does not call `self._structured_completion(...)`; that helper is built around `chat.completions.parse`/`response_format`/`.parsed`, none of which apply to the Images API. This is a deliberate difference from the other three agents, not an inconsistency — `_structured_completion` was never meant to cover every OpenAI endpoint, only structured chat completions.

### Key resolution

Identical to all three prior real agents, inherited from `BaseOpenAIAgent.__init__`: explicit `api_key` arg → `config.load_api_keys().openai_api_key` → `MissingAPIKeyError` if neither resolves.

### Image size — fixed, not configurable

`IMAGE_SIZE = "1536x1024"` (landscape) is a class-level constant, matching the shape of a 16:9-ish marketing-video frame. There is no per-call or per-project override in this spec — see Non-goals. If per-project aspect ratio ever becomes a real requirement, it needs its own spec touching `ProjectInput`, `StoryboardAgent`, and `PromptAgent`, not just this constant.

### No `response_format`

Unlike the three chat-completion agents, no `response_format` parameter is passed to `images.generate`. Current `gpt-image-1`-family models always return `b64_json` and don't accept a `response_format` override; this assumes `gpt-image-2` (per its documented `client.images.generate(model="gpt-image-2", prompt=...)` example) keeps that same contract. If that assumption is wrong once tested against a live API, it's a one-line fix to add the parameter back.

### Local image storage

`output_dir` (default `"media"`, relative to wherever the process runs) is created on construction (`mkdir(parents=True, exist_ok=True)`), mirroring `model_name`'s constructor-parameter pattern. Files are named `<candidate_id>.png` — `candidate_id` is already globally unique (`uuid4().hex[:8]`), so no `project_id`/`scene_id` needs to be threaded through `run()`; the public signature (`run(prompts: Prompts) -> Candidate`) stays identical to the stub's.

`image_url` is set to the plain filesystem path (`str(file_path)`), not a `file://` URI or data URI — the simplest form that satisfies the schema, and every downstream consumer (`ReviewAgent`, `DirectorAgent`, `VideoRenderAgent`) is currently a stub with no URL-format expectations of its own.

### Error handling

Two failure modes, both becoming `ImageAgentError` (plus the inherited `MissingAPIKeyError`, unchanged):

1. Any SDK exception during `images.generate` — auth, network, or a content-policy refusal (which the real API raises as an exception, not empty data) — wrapped as `"OpenAI image call failed: {exc}"`.
2. Empty `response.data` or a `None` `b64_json` — `"OpenAI image call returned no image data"`. This is a defensive fallback (real refusals are expected to raise, per point 1), the same spirit as the empty-`choices` guard `BaseOpenAIAgent` already has for chat completions.

File I/O (`write_bytes`) is not separately wrapped — a disk-full or permissions failure is an environment problem, not a case this agent should paper over, consistent with this project's error-handling philosophy of not guarding against scenarios that can't meaningfully be recovered from here.

### No schema-guard test applies

The offline `assert_strict_schema_safe` guard (from the shared-plumbing refactor) exists specifically for `response_format=<PydanticModel>` structured-output calls, where a Pydantic constraint like `Field(gt=0)` can compile to a JSON-schema keyword OpenAI's strict mode rejects. `images.generate` doesn't use `response_format` or any Pydantic output type at all, so this class of bug cannot occur here. Not adding a guard test for this agent is correct, not an oversight.

## Data flow

No change to the pipeline's shape. `OpenAIImageAgent` and the stub `ImageAgent` are interchangeable at whatever call site constructs `image_agent` — both take `Prompts` and return `Candidate`.

## Dependencies

None new — `openai` is already a runtime dependency. `base64` and `pathlib` are stdlib.

## Testing

No live-API test (see Non-goals). Key-free unit tests, mocking only the SDK client boundary (fake `client.images.generate` returning an object shaped like `openai`'s real response: `.data[0].b64_json`):

- Fail-fast construction with no key (reusing the already-tested `MissingAPIKeyError`).
- `test_default_model_name_is_gpt_image_2`, `test_custom_model_name_stored`.
- `test_output_dir_created_if_missing` — construct with a nonexistent nested path, assert it exists afterward.
- `test_run_calls_sdk_with_expected_model_and_size` — asserts `images.generate` is called with the right `model`, `prompt` (from `prompts.image_prompt`), and `size`.
- `test_run_writes_decoded_image_to_output_dir` — fake client returns a known base64 string; assert a file exists at `output_dir/<candidate_id>.png` with the exact decoded bytes (via `tmp_path`).
- `test_run_returns_candidate_with_file_path_as_image_url`.
- `test_run_generates_unique_candidate_ids` (ported from the existing stub test).
- `test_run_raises_on_empty_data`, `test_run_raises_on_missing_b64_json`.
- `test_run_wraps_sdk_exception`.

The existing 119 tests must continue to pass unchanged.

## Open questions for follow-up (not blocking this spec)

- Per-project configurable aspect ratio / image size, driven by real user input rather than a fixed constant — would require extending `ProjectInput`'s schema and threading it through `StoryboardAgent`/`PromptAgent` as well as `ImageAgent`, not just this agent. Deferred per Non-goals.
- `image_edit_model` (`gemini-2.5-flash-image`) remains completely unused in the codebase. Whether/when a "regenerate with edits" flow (distinct from a fresh `images.generate` call) gets built against it is a real product question, out of scope here.
- Whether generated images under `media/` should ever be cleaned up, garbage-collected, or excluded from version control (a `.gitignore` entry) is not addressed by this spec — worth resolving before this agent is actually wired into the orchestrator and starts writing files during real runs.
