# Wiring DirectorDecision.feedback into real retry-loop control — design spec

## Context

`orchestrator.py`'s scene loop (`run_pipeline`, lines ~79-118) already has working retry *mechanics*: `Decision = Literal["accept", "regenerate", "reject"]`, a bounded `for _ in range(scene.max_retries + 1)` loop, `scene.retry_count` incremented on `"regenerate"`, a terminal `PipelineError` if attempts are exhausted or the scene is ultimately rejected. This is all real and already correct — this spec does not touch it.

The actual gap: `DirectorDecision.feedback` (a string populated by both `DirectorAgent` and `NemotronDirectorAgent` today) is never read by anything. On `"regenerate"`, the loop calls `image_agent.run(scene.prompts)` again with the *exact same* `Prompts` — it re-rolls blind instead of acting on what the reviewer/director said was wrong.

Separately, `ModelConfig.image_edit_model` (`config.py:11`, `"google/gemini-2.5-flash-image"`) has existed since the config was first written but is dead — grepped across `src/`, nothing references it. No image-editing agent exists; `ReviewAgent`/`GeminiReviewAgent` only judge pass/fail, `ImageAgent`/`OpenAIImageAgent` only generate from scratch.

Chosen approach (from brainstorm): a **fixed-schedule** regenerate strategy, not a director-chosen one. A director-chosen strategy (`DirectorDecision` gaining an `edit`/`regenerate` field) was considered and rejected — it would add a new structured-output field to `NemotronDirectorAgent`'s live LLM call, stacking new risk on top of an already-unverified one (whether Elice's proxy supports structured output at all for `nemotron-3-ultra-550b-a55b` — untested as of this spec). The fixed schedule gets the same "cheap targeted fix before expensive full re-roll" behavior with zero schema changes and zero director-agent changes.

## Goals

- On a scene's first `"regenerate"` retry, use a Gemini 2.5 Flash Image **edit** of the rejected candidate's image, driven by the director's feedback — cheaper and more targeted than a full regenerate.
- On the second and any further `"regenerate"` retries, fall back to revising the scene's prompts (via `PromptAgent`, given the feedback) and regenerating from scratch.
- Both new agent types (`ImageEditAgentProtocol` and its stub) follow this project's existing stub/real, offline-by-default pattern — a stubbed `run_pipeline()` call never needs a real Gemini key.
- `PromptAgent`/`OpenAIPromptAgent` can optionally take prior feedback into account when revising prompts, without breaking their existing no-feedback call site (the pre-loop initial `prompt_agent.run(scene)` call).

## Non-goals

- Director-chosen edit-vs-regenerate strategy (`DirectorDecision` schema change) — explicitly deferred, see rejected approach above.
- Changing `scene.max_retries` / the loop's attempt-counting or termination logic — already correct, untouched.
- Fixing `NemotronDirectorAgent`'s missing `extra_body` reasoning config (the likely cause of observed Korean/foreign-language mixing in its output) — real and worth doing, but unrelated to this feature's wiring; tracked as a separate small follow-up.
- Reconciling `estimate_cost()`'s hardcoded per-agent constants against real token/API usage — an existing, unrelated limitation of the budget-tracking system.

## Design

### Protocol changes (`agents/protocols.py`)

```python
class PromptAgentProtocol(Protocol):
    def run(self, scene: Scene, feedback: str | None = None) -> Prompts: ...
    def estimate_cost(self) -> float: ...


class ImageEditAgentProtocol(Protocol):
    def run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate: ...
    def estimate_cost(self) -> float: ...
```

`feedback` on `PromptAgentProtocol.run` defaults to `None` so the existing pre-loop call (`orchestrator.py:81`, no feedback available yet at that point) is unaffected.

### New stub agent — `agents/image_edit_agent.py`

Mirrors `ImageAgent`'s existing stub shape: ignores the input candidate/prompts/feedback, returns a fresh synthetic `Candidate`.

```python
class ImageEditAgent:
    def __init__(self, model_name: str = "gemini-2.5-flash-image"):
        self.model_name = model_name

    def run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate:
        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        return Candidate(
            candidate_id=candidate_id,
            image_url=f"stub://{self.model_name}/{candidate_id}.png",
            generated_by=self.model_name,
        )

    def estimate_cost(self) -> float:
        return 0.0
```

### New real agent — `agents/gemini_image_edit_agent.py`

`BaseGeminiAgent` today only offers `_structured_interaction` (JSON-schema-constrained text output via `interactions.create`) — image editing needs image bytes back, a fundamentally different call. `GeminiImageEditAgent` bypasses the structured helper and calls `self._client` directly, the same pattern `OpenAIImageAgent` already uses to bypass `_structured_completion` for its own image-generation call.

**Blocking implementation detail**: the exact `genai.Client` call shape for `gemini-2.5-flash-image` image editing (multi-modal input: prior image + text feedback; image output extraction from the response) is not yet confirmed against real Gemini API docs. Per this project's established pattern (real NVIDIA docs were required before `scripts/nvidia_smoke_test.py` was written), real Gemini image-edit docs must be sourced before this agent is implemented — not guessed.

Shape (pending doc confirmation):

```python
class GeminiImageEditAgent(BaseGeminiAgent):
    error_cls = ImageEditAgentError
    ESTIMATED_COST_USD = <from real Gemini 2.5 Flash Image pricing, not guessed>
    base_url_config_field = "image_edit_base_url"

    def run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate:
        # reads candidate.image_url, sends image + feedback text to the edit-capable
        # endpoint, decodes the returned image, writes it out, returns a new Candidate
        ...

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

### `PromptAgent` / `OpenAIPromptAgent` feedback param

Stub `PromptAgent.run` gains the `feedback` param but ignores it (matches the stub's existing no-LLM-call nature). `OpenAIPromptAgent.run(self, scene, feedback=None)` appends feedback into `_build_messages` when present:

```python
def _build_messages(scene: Scene, feedback: str | None = None) -> list[dict]:
    ...
    user = f"Camera: {sb.camera}\n..."
    if feedback:
        user += f"\n\nThe previous attempt was rejected with this feedback — address it: {feedback}"
    return [...]
```

### Orchestrator loop change (`run_pipeline`)

New optional param `image_edit_agent: ImageEditAgentProtocol | None = None`, defaulting to stub `ImageEditAgent()` (same pattern as every other stage). The per-attempt candidate-generation logic is extracted into a small helper for readability, since the loop body now branches three ways:

```python
def _generate_candidate(
    scene: Scene,
    prompt_agent: PromptAgentProtocol,
    image_agent: ImageAgentProtocol,
    image_edit_agent: ImageEditAgentProtocol,
    running_cost: float,
    max_budget_usd: float,
) -> tuple[Candidate, float]:
    if scene.retry_count == 0:
        running_cost = _charge(running_cost, image_agent.estimate_cost(), max_budget_usd)
        return image_agent.run(scene.prompts), running_cost

    feedback = scene.candidates[-1].director_decision.feedback or ""

    if scene.retry_count == 1:
        running_cost = _charge(running_cost, image_edit_agent.estimate_cost(), max_budget_usd)
        return image_edit_agent.run(scene.candidates[-1], scene.prompts, feedback), running_cost

    running_cost = _charge(running_cost, prompt_agent.estimate_cost(), max_budget_usd)
    scene.prompts = prompt_agent.run(scene, feedback=feedback)
    running_cost = _charge(running_cost, image_agent.estimate_cost(), max_budget_usd)
    return image_agent.run(scene.prompts), running_cost
```

`run_pipeline`'s loop body replaces its current `candidate = image_agent.run(scene.prompts)` + preceding `_charge` line with:

```python
candidate, running_cost = _generate_candidate(
    scene, prompt_agent, image_agent, image_edit_agent, running_cost, project_input.max_budget_usd
)
```

Everything after that (review, director decision, append, accept/reject/retry_count handling) is unchanged.

### Factory wiring (`agents/factory.py`)

`build_real_agents` gains a `"image_edit_agent": GeminiImageEditAgent(models.image_edit_model, api_key=gemini_api_key, client=gemini_client)` entry, reusing the existing `gemini_api_key`/`gemini_client` params (no new factory params needed — `GeminiReviewAgent` already establishes that Gemini agents share one key/client).

## Testing

- `tests/test_image_edit_agent.py` (new): stub `ImageEditAgent.run` returns a valid `Candidate` with a fresh `candidate_id`, ignores inputs, `estimate_cost() == 0.0`.
- `tests/test_orchestrator.py`: extend with a scenario where a fake director rejects the first two attempts then accepts the third — assert `image_agent.run` is called on attempt 1, `image_edit_agent.run` on attempt 2 (with the correct prior candidate + feedback), and both `prompt_agent.run(scene, feedback=...)` and `image_agent.run` again on attempt 3. Assert `scene.prompts` is overwritten after the attempt-3 prompt revision.
- `tests/test_prompt_agent.py` / `tests/test_openai_prompt_agent.py`: stub ignores `feedback`; real agent's `_build_messages` includes the feedback text in the user message when provided, omits it when `None`.
- `GeminiImageEditAgent` itself: mocked-client tests only (consistent with every other real-agent test in this project — no live API calls in the test suite), added once the real Gemini call shape is confirmed.

## Open questions / follow-ups (not blocking this spec)

- Real Gemini 2.5 Flash Image edit API call shape — must be sourced from real docs before `GeminiImageEditAgent` is implemented.
- Real `ESTIMATED_COST_USD` for Gemini 2.5 Flash Image editing — needs actual pricing, not a placeholder guess.
- `NemotronDirectorAgent`'s missing `extra_body` reasoning config (chain-of-thought language-mixing) — separate small fix, not part of this spec.
- Whether a director-chosen edit-vs-regenerate strategy is worth revisiting later, once Elice's structured-output support for `nemotron-3-ultra-550b-a55b` is actually verified live.
