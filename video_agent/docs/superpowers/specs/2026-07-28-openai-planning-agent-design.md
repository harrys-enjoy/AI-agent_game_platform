# Design: OpenAIPlanningAgent (real implementation)

## Context

The video-draft-pipeline scaffold (see `docs/superpowers/plans/2026-07-28-scaffold-video-draft-pipeline.md`) currently wires six deterministic agent stubs together. None call a real model yet. This spec covers the first real agent implementation, chosen as the template pattern the other five agents will later follow: `PlanningAgent`, the first stage in the pipeline (narrative beat generation from `ProjectInput`), because it is text-only (no image/video plumbing) and lets the OpenAI SDK integration pattern — key handling, structured output, error handling — get established before touching image/video APIs.

Model keys have not arrived yet (questionnaire submitted, response pending). This spec is written so the implementation can be built and merged now, with live verification deferred until keys land.

## Goals

- Implement a real `OpenAIPlanningAgent` that produces a `Narrative` from a `ProjectInput` via the OpenAI API (model: `gpt-5.4`, matching `ModelConfig.planning_model`).
- Leave the existing stub `PlanningAgent` and its test coverage completely untouched — the two coexist behind the same `.run(project_input) -> Narrative` interface, matching the swappable-backend pattern already used for `RenderBackend` (`VeoBackend` / `SelfHostedBackend`).
- Fail fast and clearly when the API key is missing, rather than surfacing a cryptic SDK auth error mid-pipeline.

## Non-goals

- Wiring `run_pipeline`/`orchestrator.py` to actually select between the stub and the real agent. That selection mechanism (env var, explicit constructor injection, CLI flag) is a follow-up decision once more real agents exist and the pattern across all of them is clearer.
- A live, key-gated smoke test against the real OpenAI API. Deliberately deferred — there is no key to test against yet (and per the latest update, there's a real chance some requested model keys never get granted at all, so this can't be treated as "coming any day now"). Revisit once a key is available.
- Any other agent (StoryboardAgent, PromptAgent, ImageAgent, ReviewAgent, DirectorAgent). This spec establishes the pattern; each of those gets its own scoped spec later.

## Architecture

New file: `src/video_draft_pipeline/agents/openai_planning_agent.py`

```python
class MissingAPIKeyError(Exception):
    pass

class PlanningAgentError(Exception):
    pass

class OpenAIPlanningAgent:
    def __init__(self, model_name: str = "gpt-5.4", api_key: str | None = None):
        ...

    def run(self, project_input: ProjectInput) -> Narrative:
        ...
```

### Key resolution

`api_key` resolves in this order: explicit constructor argument, then `config.load_api_keys().openai_api_key`. If both are `None`, raise `MissingAPIKeyError` immediately in `__init__` — before any network call is attempted, so a misconfigured environment fails at pipeline startup, not mid-run after other agents have already done work.

### Structured output

Use the OpenAI SDK's Structured Outputs feature, passing the existing `Narrative` Pydantic model directly as `response_format`. The SDK returns an already-validated `Narrative` instance — no manual JSON parsing or retry-on-malformed-output loop needed, since the schema is enforced by the API itself.

Prompt content: a system message describing the task (generate a 4-beat narrative — setup/conflict/climax/resolution — for a game marketing video draft) plus a user message built from `project_input.preset`, `.scene_type`, `.brief`, and `.brand_requirements`. Exact prompt wording is an implementation detail, not a spec-level decision.

### Error handling

Wrap SDK-level exceptions (auth failure, network error, content refusal) and re-raise as `PlanningAgentError` with a clear message, so callers only need to handle one exception type from this agent rather than reaching into `openai`'s exception hierarchy.

## Data flow

No change to the pipeline's shape. Whatever object is constructed as `planning_agent` in `run_pipeline` only needs to satisfy `.run(project_input) -> Narrative`. `OpenAIPlanningAgent` and the existing stub `PlanningAgent` are interchangeable at that call site.

## Dependencies

Add `openai` to `pyproject.toml`'s runtime `dependencies` (not `dev`), since this is now a production dependency, not a test-only one.

## Testing

No live-API testing (see Non-goals). But since API keys may not fully materialize, the code path should still get *some* verification that doesn't depend on a real key, by mocking only the OpenAI SDK client boundary (not asserting anything about real model behavior):

- `MissingAPIKeyError` is raised at construction when no key resolves from either the constructor arg or `config.load_api_keys()`.
- The request built from a `ProjectInput` (system/user messages, `response_format=Narrative`, model name) has the expected shape — assert on the mocked client's call arguments, not on a real response.
- SDK-level exceptions raised by the mocked client get wrapped into `PlanningAgentError`.

These are unit tests only, run entirely offline as part of the normal test suite. The existing 58 tests must continue to pass unchanged, since nothing about the stub `PlanningAgent` or the orchestrator changes.

## Open questions for follow-up (not blocking this spec)

- How `run_pipeline` eventually selects stub vs. real agents (likely follows the `render_backend` injection pattern already in place).
- Whether a live, key-gated smoke test gets added once a key exists (if one ever does).
- The same design pattern (Structured Outputs + fail-fast key resolution + wrapped errors) will likely repeat for `StoryboardAgent` and `PromptAgent` (also plain OpenAI text calls) — worth revisiting whether to extract shared plumbing once 2-3 agents exist, rather than before (YAGNI).
