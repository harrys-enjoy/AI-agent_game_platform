# Real ReviewAgent (Gemini) — design spec

## Context

Of the pipeline's 7 stages, 4 (Planning/Storyboard/Prompt/Image) now have real implementations, fully wired into `run_pipeline` via optional injection, budget-guarded, and constructible in one call via `build_real_agents()`. The remaining 3 — `ReviewAgent`, `DirectorAgent`, `VideoRenderAgent` — are still pure stubs. This spec covers the first of those three.

`ReviewAgent`'s stub always returns `passed=True` with no issues, regardless of input — it never actually looks at the generated image. Its `reviewer_name` default, `"gemini-3-pro-image"`, is not a placeholder: `config.ModelConfig.review_model` uses the same name, and unlike `image_edit_model` (confirmed unused/deferred when `OpenAIImageAgent` was built), the project's model-key provisioning specifically includes `gemini-3-pro-image` — it's the actual model this agent is meant to use, confirmed against real Gemini API documentation for both image understanding and structured JSON output.

A real `ReviewAgent` needs criteria to judge an image against, but its current signature — `run(self, candidate: Candidate, prior_candidates: list[Candidate]) -> ConsistencyReview` — never receives the scene's prompt or requirements, only `Candidate` objects (image path, ID, generator name). This gap is closed as part of this spec: the signature grows a third parameter, `prompts: Prompts`, threaded from `orchestrator.py`'s existing `scene.prompts` (already set earlier in the same loop iteration).

This spec is done as a single one-shot plan — real agent class, protocol/signature changes, orchestrator injection + budget wiring, and the factory extension — rather than the 4-separate-branches pattern used for `OpenAIImageAgent`. That pattern is now a well-understood, low-risk mechanical sequence (optional injection param → protocol method → budget guard call → factory entry); repeating the full brainstorm→spec→plan→final-review cycle 4 more times for it would mostly re-pay fixed overhead rather than buy additional design rigor. The only genuinely novel part of this work — the real Gemini-backed class itself — still gets full design treatment below.

## Goals

- `ReviewAgent` gets a real implementation, `GeminiReviewAgent`, backed by the actual Gemini `interactions.create` API (confirmed via real documentation, not guessed), judging whether a generated image matches its prompt.
- `run_pipeline` can optionally use it via a `review_agent` injection parameter, following the exact pattern already established for the other 4 agents — default stays the stub, fully offline.
- Injecting the real reviewer is budget-guarded, following the exact pattern already established for the other 4.
- `build_real_agents()` can construct it too, alongside the other 4, in one call.

## Non-goals

- `DirectorAgent` and `VideoRenderAgent` remain stubs. This spec doesn't touch them.
- Using `prior_candidates` (other attempts at this scene) in the actual Gemini call. The parameter stays in the signature for API stability, but v1 only checks prompt-fidelity for the current candidate — no multi-image comparison yet. Explicitly deferred, not forgotten (see Open questions).
- The "edit vs. regenerate" decision on review failure. `DirectorAgent`'s `feedback` field already exists and is already ignored by the orchestrator's retry loop (it just calls `image_agent.run()` again with the same prompt) — that gap is real but belongs to a future `DirectorAgent`/retry-loop spec, not this one, since `ReviewAgent`'s only job is producing a verdict, not deciding what to do with it.
- Any live-API or integration test against the real Gemini API. No Gemini key exists in this environment, consistent with every other spec in this project.
- Speculative severity/editability fields on `ConsistencyReview.issues`. It stays `list[str]`, matching what the existing (stub) `DirectorAgent` and existing tests already expect. Whether a future `DirectorAgent` needs richer issue metadata is that spec's decision, not this one's.

## Design

### Gemini agent base

New file `src/video_draft_pipeline/agents/gemini_agent_base.py`, mirroring `openai_agent_base.py`'s shape for the `google-genai` SDK:

```python
from google import genai
from pydantic import BaseModel

from .. import config
from .openai_agent_base import MissingAPIKeyError


class BaseGeminiAgent:
    error_cls: type[Exception]

    def __init__(self, model_name: str, api_key: str | None = None, client: genai.Client | None = None):
        resolved_key = api_key or config.load_api_keys().gemini_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No Gemini API key found: pass api_key explicitly or set GEMINI_API_KEY."
            )
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or genai.Client(api_key=resolved_key)

    def _structured_interaction(self, input_content: list[dict], response_schema: type[BaseModel]) -> BaseModel:
        try:
            interaction = self._client.interactions.create(
                model=self.model_name,
                input=input_content,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema.model_json_schema(),
                },
            )
        except Exception as exc:
            raise self.error_cls(f"Gemini call failed: {exc}") from exc
        try:
            return response_schema.model_validate_json(interaction.output_text)
        except Exception as exc:
            raise self.error_cls(f"Gemini call returned unparseable output: {exc}") from exc
```

`MissingAPIKeyError` is reused from `openai_agent_base.py` rather than duplicated — it's a generic "no key resolved" signal with no provider-specific behavior, and reuse avoids touching the 4 already-shipped OpenAI agent files. The import reads a little oddly (a Gemini file importing from an "openai" module) but is a one-line, zero-risk reuse over inventing an identical second exception type.

`_structured_interaction` mirrors `BaseOpenAIAgent._structured_completion`'s shape: real Gemini structured output (confirmed via documentation) works by passing a JSON schema in `response_format` and parsing `interaction.output_text` back into the Pydantic model afterward — less automatic than OpenAI's `.parse()`, but genuinely structured, not prompt-engineered-and-hoped-for.

### `GeminiReviewAgent`

New file `src/video_draft_pipeline/agents/gemini_review_agent.py`:

```python
import base64
from pathlib import Path

from pydantic import BaseModel

from ..schema import Candidate, ConsistencyReview, Prompts
from .gemini_agent_base import BaseGeminiAgent


class ReviewAgentError(Exception):
    pass


class ReviewVerdict(BaseModel):
    passed: bool
    issues: list[str]


class GeminiReviewAgent(BaseGeminiAgent):
    error_cls = ReviewAgentError
    ESTIMATED_COST_USD = 0.02

    def __init__(self, model_name: str = "gemini-3-pro-image", api_key: str | None = None, client=None):
        super().__init__(model_name, api_key, client)

    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
        image_bytes = Path(candidate.image_url).read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        input_content = [
            {
                "type": "text",
                "text": (
                    "You are reviewing an AI-generated image for a game marketing video scene. "
                    f"The image was generated from this prompt: {prompts.image_prompt}\n"
                    "Judge whether the image faithfully matches the prompt. Respond with passed=true "
                    "only if the image clearly matches; otherwise passed=false and list concrete issues."
                ),
            },
            {"type": "image", "data": image_b64, "mime_type": "image/png"},
        ]

        verdict = self._structured_interaction(input_content, ReviewVerdict)
        return ConsistencyReview(reviewed_by=self.model_name, passed=verdict.passed, issues=verdict.issues)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

`ESTIMATED_COST_USD = 0.02` is a flat placeholder, same convention as the other 4 real agents — higher than the chat-completion agents (`0.01`/`0.005`) since `gemini-3-pro-image` is the pricier dedicated-image-model tier even for pure understanding calls, lower than `OpenAIImageAgent`'s `0.04` since reviewing costs less than generating.

`ConsistencyReview.reviewed_by` is set to `self.model_name` (matching the pattern the stub already uses — `reviewer_name` stored and echoed back).

### Signature extension: `prompts` threaded through

`ReviewAgentProtocol` (new, in `agents/protocols.py`):

```python
@runtime_checkable
class ReviewAgentProtocol(Protocol):
    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview: ...
    def estimate_cost(self) -> float: ...
```

Stub `ReviewAgent` (`agents/review_agent.py`) gains the third parameter (still ignored — the stub never looks at anything) and `estimate_cost`:

```python
class ReviewAgent:
    def __init__(self, reviewer_name: str = "gemini-3-pro-image"):
        self.reviewer_name = reviewer_name

    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
        return ConsistencyReview(reviewed_by=self.reviewer_name, passed=True, issues=[])

    def estimate_cost(self) -> float:
        return 0.0
```

`orchestrator.py`'s call site changes from `review_agent.run(candidate, scene.candidates)` to `review_agent.run(candidate, scene.candidates, scene.prompts)`. `scene.prompts` is already set earlier in the same loop iteration, so nothing new needs threading through beyond the extra argument.

This touches two already-shipped files (`review_agent.py`, `orchestrator.py`'s call site) and one already-shipped test (`tests/test_orchestrator.py`'s `FailingReviewAgent` subclass, whose `run` override needs the third parameter to keep matching). All are small, mechanical, signature-only changes — no behavior change to the stub or to any already-passing assertion.

### Orchestrator injection + budget guard

`run_pipeline` gains one more optional parameter, same pattern as the other 4:

```python
def run_pipeline(
    project_input: ProjectInput,
    render_backend: RenderBackend | None = None,
    model_config: ModelConfig | None = None,
    planning_agent: PlanningAgentProtocol | None = None,
    storyboard_agent: StoryboardAgentProtocol | None = None,
    prompt_agent: PromptAgentProtocol | None = None,
    image_agent: ImageAgentProtocol | None = None,
    review_agent: ReviewAgentProtocol | None = None,
) -> Project:
    ...
    review_agent = review_agent or ReviewAgent(models.review_model)
    ...
```

Inside the retry loop, a guard call right before the (now 3-arg) review call, same shape as the existing image-agent guard:

```python
    for _ in range(max_attempts):
        running_cost = _charge(running_cost, image_agent.estimate_cost(), project_input.max_budget_usd)
        candidate = image_agent.run(scene.prompts)
        running_cost = _charge(running_cost, review_agent.estimate_cost(), project_input.max_budget_usd)
        candidate.consistency_review = review_agent.run(candidate, scene.candidates, scene.prompts)
        candidate.director_decision = director_agent.run(scene, candidate.consistency_review)
        ...
```

Fresh guard on every retry attempt, same reasoning as the image-agent guard: unbounded review cost shouldn't be possible for a scene stuck retrying either. `DirectorAgent`/`VideoRenderAgent` construction is untouched — still stubs, still out of scope.

### Factory extension and rename

`build_real_agents()` currently has one implicit provider (`api_key`, `client` both meaning "the OpenAI ones"). With a second provider entering the picture, that's renamed to `openai_api_key`/`openai_client`, with `gemini_api_key`/`gemini_client` added alongside:

```python
def build_real_agents(
    openai_api_key: str | None = None,
    gemini_api_key: str | None = None,
    output_dir: str | Path = "media",
    model_config: ModelConfig | None = None,
    openai_client: OpenAI | None = None,
    gemini_client: genai.Client | None = None,
) -> dict[str, object]:
    models = model_config or ModelConfig()
    return {
        "planning_agent": OpenAIPlanningAgent(models.planning_model, api_key=openai_api_key, client=openai_client),
        "storyboard_agent": OpenAIStoryboardAgent(models.storyboard_model, api_key=openai_api_key, client=openai_client),
        "prompt_agent": OpenAIPromptAgent(models.prompt_model, api_key=openai_api_key, client=openai_client),
        "image_agent": OpenAIImageAgent(models.image_model, output_dir=output_dir, api_key=openai_api_key, client=openai_client),
        "review_agent": GeminiReviewAgent(models.review_model, api_key=gemini_api_key, client=gemini_client),
    }
```

This is a breaking rename of `factory.py`'s public parameters, done deliberately: the factory was only shipped in the immediately prior branch and has no callers outside its own tests yet, so renaming now (cheap) beats carrying a provider-ambiguous `api_key` name forward once multiple providers exist permanently. Usage becomes `run_pipeline(project_input, **build_real_agents(openai_api_key="...", gemini_api_key="..."))` — still one call, now covering 5 agents across 2 providers.

## Testing

- `tests/agents/test_gemini_agent_base.py` (new, mirrors `test_openai_agent_base.py`): missing-key fail-fast, explicit-key precedence, env-var resolution, `_structured_interaction`'s error wrapping (SDK exception → `error_cls`; malformed/non-schema JSON → `error_cls`).
- `tests/agents/test_gemini_review_agent.py` (new, mirrors the OpenAI agent test files): constructor tests (missing key, key precedence, default/custom model name, `estimate_cost() == 0.02`); `run()` tests with a mocked `client.interactions.create` (correct `input_content` shape — prompt text + base64 image, no prior-candidate images sent; correct parsing of a valid `ReviewVerdict` response into `ConsistencyReview`; SDK exception wrapped as `ReviewAgentError`; malformed JSON wrapped as `ReviewAgentError`).
- `tests/agents/test_review_agent.py` (existing, stub): updated for the 3-arg `run()`; add `estimate_cost() == 0.0`.
- `tests/agents/test_protocols.py` (existing): add `ReviewAgentProtocol` conformance for both `ReviewAgent` and `GeminiReviewAgent`.
- `tests/test_orchestrator.py` (existing): fix `FailingReviewAgent`'s `run()` for the 3rd parameter; add an injected-fake-review-agent-overrides-default test; add a budget-blocking test for `review_agent` (same `run_called`-flag pattern as the existing `Expensive*Agent` tests); add one real-`GeminiReviewAgent`-with-mocked-client smoke test proving the real class's signature works through the orchestrator end-to-end.
- `tests/agents/test_factory.py` (existing): rename `api_key`/`client` references to `openai_api_key`/`openai_client`; add `gemini_api_key`/`gemini_client` threading test for `review_agent`; update the "exactly the expected keys" test to 5 keys; update the end-to-end integration test to also mock a Gemini client's `interactions.create` so the full `run_pipeline(**build_real_agents(...))` path (now including real review) still runs fully offline.
- README: rename the factory usage example's params; document the new `review_agent` injection parameter alongside the existing 4.

No live-API tests, consistent with every other spec in this project.

## Open questions / follow-ups (not blocking this spec)

- Using `prior_candidates` for real cross-attempt visual consistency checking, not just prompt-fidelity — deferred per your v1 decision, cheap to add later without another signature change.
- The "edit vs. regenerate" decision on review failure (via `gemini-2.5-flash-image`'s editing capability) and wiring `DirectorAgent.feedback` into the retry loop — this is the natural next spec, and needs `ReviewAgent` to be real first (no point editing based on feedback from a stub that never fails).
- `VideoRenderAgent`/`VeoBackend` remain fully stubbed, unrelated to this spec.
