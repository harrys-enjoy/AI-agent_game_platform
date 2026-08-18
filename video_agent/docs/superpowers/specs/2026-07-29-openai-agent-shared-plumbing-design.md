# Design: Shared plumbing for OpenAI-backed agents

## Context

Three real agents now exist (`OpenAIPlanningAgent`, `OpenAIStoryboardAgent`, `OpenAIPromptAgent`), each independently implementing identical key-resolution/client-injection constructors and an identical SDK-call-plus-refusal-check pattern in `run()`. This duplication was deliberately deferred twice ("revisit after a third real agent exists") and flagged again in the third agent's final review, which also identified two small bugs latent in all three copies:

- **M1:** `completion.choices[0]` is accessed with no guard; an empty `choices` list raises a raw `IndexError` instead of the agent's own exception type, in all three agents identically.
- **M3:** nothing prevents a future edit to a `response_format` type from silently reintroducing the exact class of bug that shipped in `OpenAIStoryboardAgent` (`Field(gt=0)` emitting an `exclusiveMinimum` keyword OpenAI's strict schema subset rejects, failing every live call) — that bug was only caught by human review, not by the test suite.

This spec extracts the shared plumbing into one base class and fixes both bugs as part of the same change, since all three touch the exact code being restructured.

## Goals

- Eliminate the duplicated constructor and SDK-call/refusal-check logic across all three real agents via a shared `BaseOpenAIAgent`.
- Fix M1: an empty `choices` list raises the agent's own exception type, not a raw `IndexError`.
- Fix M3: add an offline, key-free test that would have caught the `Field(gt=0)` bug automatically, applied to every response-format type currently in use (`Narrative`, `Prompts`, `SceneDraft`, `StoryboardDraft`).
- Preserve every existing public behavior exactly: all three agents' `.run()` signatures, return types, and exception types are unchanged. This is a pure internal refactor from the caller's perspective.
- Keep the three agent-specific exception classes (`PlanningAgentError`, `StoryboardAgentError`, `PromptAgentError`) distinct, not unified — callers can still tell which pipeline stage failed.

## Non-goals

- Changing any agent's `run()` signature, return type, or exception type.
- Extracting the prompt-building (`_build_messages`) logic — fully agent-specific, nothing to share.
- Orchestrator wiring (still deferred, as in all three prior specs).
- Consolidating the per-test-file `_fake_completion`/`_scene`/`_draft`-style test helpers across the three test files. Test-code duplication for clarity is a different concern from production-code duplication; each test file staying freestanding and readable in isolation is a reasonable trade, and the review didn't flag this. Only the new schema-guard helper (genuinely new shared logic, not a duplicate of existing code) gets its own shared module.
- Building `ImageAgent` or any other new agent — this refactor is a prerequisite step, done first per the human partner's explicit call.

## Architecture

New file: `src/video_draft_pipeline/agents/openai_agent_base.py`

```python
from openai import OpenAI
from pydantic import BaseModel

from .. import config


class MissingAPIKeyError(Exception):
    pass


class BaseOpenAIAgent:
    error_cls: type[Exception]

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        client: OpenAI | None = None,
    ):
        resolved_key = api_key or config.load_api_keys().openai_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No OpenAI API key found: pass api_key explicitly or set OPENAI_API_KEY."
            )
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or OpenAI(api_key=resolved_key)

    def _structured_completion(
        self, messages: list[dict], response_format: type[BaseModel]
    ) -> BaseModel:
        try:
            completion = self._client.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                response_format=response_format,
            )
        except Exception as exc:
            raise self.error_cls(f"OpenAI call failed: {exc}") from exc
        if not completion.choices:
            raise self.error_cls("OpenAI call returned no choices")
        message = completion.choices[0].message
        if message.parsed is None:
            raise self.error_cls(
                f"OpenAI call returned no parsed result: {message.refusal or 'empty response'}"
            )
        return message.parsed
```

### Migration of the three existing agents

Each agent's file keeps its own `XAgentError` class, sets `error_cls = XAgentError` on its subclass, and its `__init__`/`run()` shrink to:

```python
# openai_planning_agent.py
from .openai_agent_base import BaseOpenAIAgent, MissingAPIKeyError  # re-exported for existing importers, see below


class PlanningAgentError(Exception):
    pass


class OpenAIPlanningAgent(BaseOpenAIAgent):
    error_cls = PlanningAgentError

    def __init__(self, model_name: str = "gpt-5.4", api_key: str | None = None, client: OpenAI | None = None):
        super().__init__(model_name, api_key, client)

    def run(self, project_input: ProjectInput) -> Narrative:
        return self._structured_completion(_build_messages(project_input), Narrative)
```

`OpenAIStoryboardAgent.run()` and `OpenAIPromptAgent.run()` follow the same shape: call `self._structured_completion(...)`, then apply their existing agent-specific post-processing (beat-alignment/weight validation + `_drafts_to_scenes` conversion for storyboard; the `required_elements` append for prompt) to the returned object before returning it.

`MissingAPIKeyError`'s import path changes for the two agents that currently import it from `openai_planning_agent.py` — both switch to importing it from `openai_agent_base.py` directly (the canonical, correct location now), rather than being re-exported through `openai_planning_agent.py`. `openai_planning_agent.py` itself also switches to importing it from the new module instead of defining it. This project's stated convention is to avoid re-export shims, so no backward-compatible re-export is kept anywhere — all three agent files' imports get updated directly, and so does anything importing it in tests (see Testing).

## Data flow

Unchanged for every caller. `run_pipeline()` (currently only constructing the stub agents) is unaffected, since orchestrator wiring remains out of scope. Anything that already imports `OpenAIPlanningAgent`/`OpenAIStoryboardAgent`/`OpenAIPromptAgent` and calls `.run(...)` sees identical behavior — same inputs produce the same outputs, same failure modes raise the same exception types.

## Error handling

`BaseOpenAIAgent._structured_completion` now handles three failure modes uniformly instead of two per agent, closing the M1 gap:

1. Any SDK-level exception (auth, network, etc.) → `self.error_cls`.
2. **New:** an empty `choices` list → `self.error_cls` (previously an unguarded `IndexError`).
3. A refusal (`message.parsed is None`) → `self.error_cls`.

Each agent's own post-processing (e.g. `StoryboardAgent`'s beat-alignment check, the `duration_weight > 0` check, the `_drafts_to_scenes` `ValidationError` wrap) stays exactly where it is today, in each agent's own `run()`, since those checks are agent-specific and don't belong in the shared base.

## Testing

Three categories, all offline, no API key required:

1. **Base class tests** (new file `tests/agents/test_openai_agent_base.py`): construct a minimal dummy subclass (`class _DummyAgent(BaseOpenAIAgent): error_cls = _DummyError`) and test `BaseOpenAIAgent` directly — key resolution (missing/explicit/env-fallback, mirroring the pattern already tested three times over), `_structured_completion`'s happy path, its SDK-exception wrap, its new empty-choices guard, and its refusal check. Roughly 7-8 tests.
2. **Wire-schema guard** (new non-test helper `tests/agents/_schema_guard.py`, function `assert_strict_schema_safe(model: type[BaseModel]) -> None`): walks `model.model_json_schema()` recursively (including nested `$defs`) and fails with a clear message if any property carries a keyword outside OpenAI's strict Structured Outputs subset (`exclusiveMinimum`, `exclusiveMaximum`, `minimum`, `maximum`, `minLength`, `maxLength`, `pattern`, `format`, `multipleOf`). Uses the public `model_json_schema()`, not OpenAI SDK's private `to_strict_json_schema` — an approximation, not a perfect simulation of the SDK's exact transform, but one that would have caught the `Field(gt=0)` bug automatically and doesn't depend on private API surface. One new test added to each existing agent's test file: `test_narrative_response_format_is_strict_schema_safe` (planning), `test_storyboard_draft_response_format_is_strict_schema_safe` + `test_scene_draft_response_format_is_strict_schema_safe` (storyboard, since both are used as/nested in `response_format`), `test_prompts_response_format_is_strict_schema_safe` (prompt).
3. **Regression:** all three existing agent test files (13+18+13... — see the three prior plans for exact per-file counts, 105 total pre-refactor across the whole suite) must continue to pass with **no assertion changes**. The one permitted per-file edit is mechanical: each of the three test files currently does `from video_draft_pipeline.agents.openai_planning_agent import MissingAPIKeyError` (since that was `MissingAPIKeyError`'s original home); after the move, that import line changes to `from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError` in all three files, per the no-re-export-shim stance above — nothing else in any existing test changes. Any change beyond that one import-path correction and the new schema-guard test additions would indicate the refactor changed behavior, which is out of scope.

Net new tests: ~7-8 (base class) + 4 (schema guard) = roughly 11-12, on top of the 105 that must stay green untouched.

## Open questions for follow-up (not blocking this spec)

- `ImageAgent`'s real implementation is next, and is a different shape entirely (image generation, not a chat completion) — it's unclear yet whether `BaseOpenAIAgent` applies to it at all, or whether image generation needs its own base/pattern. Assess when that spec is written.
- Whether `_structured_completion`'s generic error message ("OpenAI call failed") should become more specific per agent (e.g. via a class-level label) is left as-is for now — the exception *type* already identifies the failing stage, and adding a label is easy to do later without breaking anything if it turns out to matter.
