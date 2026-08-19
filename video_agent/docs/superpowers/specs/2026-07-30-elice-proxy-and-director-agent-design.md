# Elice proxy retrofit + real DirectorAgent (Nemotron) — design spec

## Context

The bootcamp does not provision direct OpenAI/Google/NVIDIA API access. All model access goes through 엘리스's own OpenAI-compatible proxy gateway (`mlapi.run`-style `base_url`, Elice-issued `api_key`, provider-prefixed model strings like `"openai/gpt-5.4"` or `"google/gemini-3-pro-image-preview"`). This was discovered only now, verified against real Elice documentation pasted for `gpt-5.4`, `gpt-5-mini`, `gpt-image-2`, `gemini-2.5-flash-image`, `gemini-3-pro-image`, and `nemotron-3-ultra` (served as `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4`).

This means the 4 already-shipped real agents (`OpenAIPlanningAgent`, `OpenAIStoryboardAgent`, `OpenAIPromptAgent`, `OpenAIImageAgent`) plus `GeminiReviewAgent` all have a latent bug: `BaseOpenAIAgent`/`BaseGeminiAgent` construct their SDK clients with no `base_url` override at all, so they'd hit the real vendor endpoints rather than Elice's proxy, and would fail against real Elice-issued keys. Additionally, every agent's `model_name` string is missing the provider prefix Elice's router requires, and `review_model`'s existing default (`"gemini-3-pro-image"`) is missing Elice's `-preview` suffix.

Separately, of the pipeline's 7 stages, `DirectorAgent` is still a pure stub — it never makes an LLM call, just applies a fixed rule (`review.passed` → accept; retries exhausted → reject; otherwise → regenerate). `config.ModelConfig.director_model`'s existing default, `"nemotron-3-ultra"`, was not a placeholder — it's Elice's real Nemotron-3-Ultra-550B model, confirmed via Elice's own documentation, which explicitly states this model is served through the same "OpenAI 호환 Chat Completions" interface with Structured Output support.

Since both problems touch the same two base classes (`BaseOpenAIAgent`/`BaseGeminiAgent`) and `DirectorAgent` needs the Elice proxy plumbing to work at all, this spec covers both in one pass: retrofit the base_url/model-string handling first, then build the real `DirectorAgent` on top of the corrected foundation. Building `DirectorAgent` against today's `BaseOpenAIAgent` and retrofitting it immediately afterward would mean touching the same code twice for no benefit.

## Goals

- `BaseOpenAIAgent`/`BaseGeminiAgent` support a configurable `base_url`, resolved the same way `api_key` already is (explicit param → env var → `None`/SDK default).
- The 4 existing real OpenAI-family agents + `GeminiReviewAgent` are retrofitted to use it, with corrected provider-prefixed default model-name strings.
- `config.py`'s `ModelConfig` defaults and `ApiKeys` gain per-stage `base_url` fields.
- `DirectorAgent` gets a real implementation, `NemotronDirectorAgent`, backed by Elice's Nemotron-3-Ultra endpoint, making a genuine accept/regenerate/reject judgment call instead of the stub's fixed rule — while preserving the stub's retry-cap safety invariant deterministically.
- `run_pipeline` can optionally use it via a `director_agent` injection parameter, following the exact pattern already established for the other 5 agents.
- Injecting the real director is budget-guarded, following the exact pattern already established for the other 5.
- `build_real_agents()` can construct it too, alongside the other 5, in one call.

## Non-goals

- `VideoRenderAgent`/`VeoBackend` remain stubs. Confirmed separately: Veo 3.1 is accessed directly (out of pocket), not through Elice, so it's unaffected by this spec's proxy retrofit.
- Any live-API or integration test against Elice's real endpoints. No real keys exist in this environment yet (still on standby per the bootcamp), consistent with every other spec in this project.
- The "edit vs. regenerate" decision actually driving different orchestrator behavior (e.g. real image editing on `"regenerate"` vs. today's identical `image_agent.run()` retry). `DirectorDecision.feedback` continues to exist and continues to be ignored by the retry loop. That's the next spec's job, same as noted in the `ReviewAgent` spec.
- Reasoning-mode tuning (`enable_thinking`, `medium_effort`, `force_nonempty_content`) for Nemotron. Only the two parameters Elice's docs recommend for best general performance (`temperature=1.0`, `top_p=0.95`) are set explicitly; reasoning stays at its default (ON).
- A shared/consolidated base_url per provider. Each stage gets its own `ApiKeys` field, since the evidence (a distinct leaked deployment ID for `gpt-image-2` vs. a shared placeholder for `gpt-5.4`/`gpt-5-mini`) doesn't confirm whether Elice shares one gateway per provider or issues one per model. Per-stage is the safe default; if it later turns out several stages truly share one URL, setting the same env var value for each costs nothing.

## Design

### Config layer (`config.py`)

`ModelConfig` model-string defaults corrected to Elice's real provider-prefixed IDs:

```python
@dataclass
class ModelConfig:
    planning_model: str = "openai/gpt-5.4"
    storyboard_model: str = "openai/gpt-5.4"
    prompt_model: str = "openai/gpt-5-mini"
    image_model: str = "openai/gpt-image-2"
    image_edit_model: str = "google/gemini-2.5-flash-image"
    review_model: str = "google/gemini-3-pro-image-preview"
    director_model: str = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4"
    render_backend: str = "veo-3.1-fast"
```

`ApiKeys` gains one `base_url` field per stage, plus `nemotron_api_key` (already present) is now load-bearing:

```python
@dataclass
class ApiKeys:
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    nemotron_api_key: str | None = None
    planning_base_url: str | None = None
    storyboard_base_url: str | None = None
    prompt_base_url: str | None = None
    image_base_url: str | None = None
    review_base_url: str | None = None
    director_base_url: str | None = None


def load_api_keys() -> ApiKeys:
    return ApiKeys(
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        nemotron_api_key=os.environ.get("NEMOTRON_API_KEY"),
        planning_base_url=os.environ.get("OPENAI_PLANNING_BASE_URL"),
        storyboard_base_url=os.environ.get("OPENAI_STORYBOARD_BASE_URL"),
        prompt_base_url=os.environ.get("OPENAI_PROMPT_BASE_URL"),
        image_base_url=os.environ.get("OPENAI_IMAGE_BASE_URL"),
        review_base_url=os.environ.get("GEMINI_REVIEW_BASE_URL"),
        director_base_url=os.environ.get("NEMOTRON_DIRECTOR_BASE_URL"),
    )
```

None of these `base_url` fields are required — when unset, the resolved value stays `None` and the SDK client falls back to its real default endpoint, which is what every existing test already relies on (mocked/faked clients, no real network calls).

### Base class changes (`BaseOpenAIAgent`/`BaseGeminiAgent`)

Both gain a `base_url: str | None = None` constructor param and a `base_url_config_field: str` class attribute (declared like `error_cls`, set by each concrete subclass) naming which `ApiKeys` field to fall back to:

```python
class BaseOpenAIAgent:
    error_cls: type[Exception]
    base_url_config_field: str

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        resolved_key = api_key or config.load_api_keys().openai_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No OpenAI API key found: pass api_key explicitly or set OPENAI_API_KEY."
            )
        resolved_base_url = base_url or getattr(config.load_api_keys(), self.base_url_config_field, None)
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or OpenAI(api_key=resolved_key, base_url=resolved_base_url)

    def _structured_completion(
        self, messages: list[dict], response_format: type[BaseModel], **extra_kwargs
    ) -> BaseModel:
        try:
            completion = self._client.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                response_format=response_format,
                **extra_kwargs,
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

`OpenAI(base_url=None)` is equivalent to omitting the param (the SDK's own default), so no extra guarding is needed there. `_structured_completion` gains `**extra_kwargs`, forwarded straight to `chat.completions.parse(...)` — needed so `NemotronDirectorAgent` can pass `temperature=1.0, top_p=0.95` (Elice/NVIDIA's own recommended values) without adding that complexity to every other stage.

`BaseGeminiAgent` gets the same `base_url`/`base_url_config_field` treatment, but `genai.Client` takes the override differently and doesn't tolerate an explicit `None`:

```python
class BaseGeminiAgent:
    error_cls: type[Exception]
    base_url_config_field: str

    def __init__(self, model_name: str, api_key: str | None = None, client: genai.Client | None = None, base_url: str | None = None):
        resolved_key = api_key or config.load_api_keys().gemini_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No Gemini API key found: pass api_key explicitly or set GEMINI_API_KEY."
            )
        resolved_base_url = base_url or getattr(config.load_api_keys(), self.base_url_config_field, None)
        http_options = {"base_url": resolved_base_url} if resolved_base_url else None
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or genai.Client(api_key=resolved_key, http_options=http_options)
```

### Retrofit of the 4 existing real OpenAI-family agents

Each gets a `base_url_config_field` class attribute, a `base_url: str | None = None` constructor param forwarded to `super().__init__(...)`, and a corrected default `model_name` string. Mechanical and identical across all 4; `OpenAIPlanningAgent` shown as the representative example:

```python
class OpenAIPlanningAgent(BaseOpenAIAgent):
    error_cls = PlanningAgentError
    ESTIMATED_COST_USD = 0.01
    base_url_config_field = "planning_base_url"

    def __init__(
        self,
        model_name: str = "openai/gpt-5.4",
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)
```

The same shape applies to:
- `OpenAIStoryboardAgent` — `base_url_config_field = "storyboard_base_url"`, default `model_name = "openai/gpt-5.4"`.
- `OpenAIPromptAgent` — `base_url_config_field = "prompt_base_url"`, default `model_name = "openai/gpt-5-mini"`.
- `OpenAIImageAgent` — `base_url_config_field = "image_base_url"`, default `model_name = "openai/gpt-image-2"` (its extra `output_dir` param is untouched).

### Retrofit of `GeminiReviewAgent`

Same treatment, on `BaseGeminiAgent`:

```python
class GeminiReviewAgent(BaseGeminiAgent):
    error_cls = ReviewAgentError
    ESTIMATED_COST_USD = 0.02
    base_url_config_field = "review_base_url"

    def __init__(
        self,
        model_name: str = "google/gemini-3-pro-image-preview",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)
```

`run()` and `estimate_cost()` are unchanged — this is purely a construction-time/config change.

### `NemotronDirectorAgent`

New file `src/video_draft_pipeline/agents/nemotron_director_agent.py`. Reuses `BaseOpenAIAgent` directly — Elice's own model spec sheet for Nemotron-3-Ultra states it's served via "OpenAI 호환 Chat Completions" with Structured Output support, the same interface the other 4 agents already use, so no new base class is needed (unlike `GeminiReviewAgent`, which needed one because the Gemini SDK's shape is genuinely different).

```python
from openai import OpenAI
from pydantic import BaseModel

from ..schema import ConsistencyReview, Decision, DirectorDecision, Scene
from .openai_agent_base import BaseOpenAIAgent


def _build_messages(scene: Scene, review: ConsistencyReview) -> list[dict]:
    system = (
        "You are the creative director for a game marketing video draft. You "
        "decide whether a generated scene image should be accepted, "
        "regenerated, or rejected outright, based on a consistency review."
    )
    issues = "; ".join(review.issues) or "none"
    user = (
        f"Scene: {scene.scene_id} ({scene.beat_id})\n"
        f"Review passed: {review.passed}\n"
        f"Review issues: {issues}\n"
        f"Retry count so far: {scene.retry_count} / max {scene.max_retries}\n"
        "Decide: accept (image is usable as-is), regenerate (image should be "
        "attempted again), or reject (give up on this scene). Give a short "
        "reason in feedback."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


class DirectorAgentError(Exception):
    pass


class DirectorVerdict(BaseModel):
    decision: Decision
    feedback: str | None = None


class NemotronDirectorAgent(BaseOpenAIAgent):
    error_cls = DirectorAgentError
    base_url_config_field = "director_base_url"
    ESTIMATED_COST_USD = 0.03

    def __init__(
        self,
        model_name: str = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4",
        api_key: str | None = None,
        client: OpenAI | None = None,
        base_url: str | None = None,
    ):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision:
        verdict = self._structured_completion(
            _build_messages(scene, review),
            DirectorVerdict,
            temperature=1.0,
            top_p=0.95,
        )
        decision = verdict.decision
        if scene.retry_count >= scene.max_retries:
            decision = "reject"
        return DirectorDecision(decision=decision, feedback=verdict.feedback, decided_by=self.model_name)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

The LLM is always called — even once the retry cap is reached — so `feedback` still carries a real explanation. But the returned `decision` is deterministically forced to `"reject"` once `scene.retry_count >= scene.max_retries`, regardless of what the model answered. This preserves the stub's existing hard safety invariant (the orchestrator's retry loop depends on scenes terminating) without relying on the LLM reliably respecting a numeric constraint given only as context.

`ESTIMATED_COST_USD = 0.03` is a flat placeholder, same convention as the other 5 real agents — between `OpenAIStoryboardAgent`'s `0.01` and `OpenAIImageAgent`'s `0.04`, reflecting that Nemotron-3-Ultra (550B) is a larger reasoning model than the chat-completion stages but isn't generating binary image data.

### `DirectorAgentProtocol` and stub update

`agents/protocols.py` gains:

```python
@runtime_checkable
class DirectorAgentProtocol(Protocol):
    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision: ...
    def estimate_cost(self) -> float: ...
```

Stub `DirectorAgent` (`agents/director_agent.py`) gains `estimate_cost() -> 0.0`; its `run()` logic is unchanged (it's the existing fixed-rule behavior, and stays the default when nothing is injected).

### Orchestrator injection + budget guard

`run_pipeline` gains a `director_agent: DirectorAgentProtocol | None = None` param, defaulting to the existing stub — same pattern as the other 5:

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
    director_agent: DirectorAgentProtocol | None = None,
) -> Project:
    ...
    director_agent = director_agent or DirectorAgent(models.director_model)
    ...
```

Inside the retry loop, a guard call right before the existing `director_agent.run(...)` call, same shape as the `image_agent`/`review_agent` guards:

```python
        for _ in range(max_attempts):
            running_cost = _charge(running_cost, image_agent.estimate_cost(), project_input.max_budget_usd)
            candidate = image_agent.run(scene.prompts)
            running_cost = _charge(running_cost, review_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.consistency_review = review_agent.run(candidate, scene.candidates, scene.prompts)
            running_cost = _charge(running_cost, director_agent.estimate_cost(), project_input.max_budget_usd)
            candidate.director_decision = director_agent.run(scene, candidate.consistency_review)
            ...
```

Fresh guard on every retry attempt, same reasoning as the existing two: a scene stuck retrying shouldn't be able to run up unbounded director cost either. `VideoRenderAgent` construction is untouched — still a stub, still out of scope.

### Factory extension

`build_real_agents()` gains `nemotron_api_key`/`nemotron_client` params and a `director_agent` entry. No new `base_url` parameters are needed on the factory itself — each agent already resolves its own `base_url` from env when not given an explicit override, the same way `api_key` already works today:

```python
def build_real_agents(
    openai_api_key: str | None = None,
    gemini_api_key: str | None = None,
    nemotron_api_key: str | None = None,
    output_dir: str | Path = "media",
    model_config: ModelConfig | None = None,
    openai_client: OpenAI | None = None,
    gemini_client: genai.Client | None = None,
    nemotron_client: OpenAI | None = None,
) -> dict[str, object]:
    models = model_config or ModelConfig()
    return {
        "planning_agent": OpenAIPlanningAgent(models.planning_model, api_key=openai_api_key, client=openai_client),
        "storyboard_agent": OpenAIStoryboardAgent(models.storyboard_model, api_key=openai_api_key, client=openai_client),
        "prompt_agent": OpenAIPromptAgent(models.prompt_model, api_key=openai_api_key, client=openai_client),
        "image_agent": OpenAIImageAgent(models.image_model, output_dir=output_dir, api_key=openai_api_key, client=openai_client),
        "review_agent": GeminiReviewAgent(models.review_model, api_key=gemini_api_key, client=gemini_client),
        "director_agent": NemotronDirectorAgent(models.director_model, api_key=nemotron_api_key, client=nemotron_client),
    }
```

`NemotronDirectorAgent` uses `OpenAI` as its client type (it's `BaseOpenAIAgent`-backed), so `nemotron_client` is typed the same as `openai_client`/not a new SDK dependency.

### README

"Real agent injection" section updated to list all 6 injectable agents (`planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`, `review_agent`, `director_agent`), noting only `VideoRenderAgent` has no real implementation yet. The `build_real_agents()` usage example gains `nemotron_api_key="..."`. Env var documentation extended to mention the new per-stage `*_BASE_URL` variables (all optional, unset by default).

## Testing

- `tests/agents/test_openai_agent_base.py` / `test_gemini_agent_base.py`: new tests for `base_url` resolution order (explicit param > env var via `base_url_config_field` > `None`), verified via a subclass with a known `base_url_config_field` and either inspecting the constructed client's `base_url` attribute or injecting a spy client constructor.
- Each of the 5 retrofitted real agent test files: a test that the corrected default `model_name` matches the new provider-prefixed string, and that `base_url_config_field` resolves the right `ApiKeys` field (e.g. setting `OPENAI_IMAGE_BASE_URL` and constructing `OpenAIImageAgent()` with no explicit client results in a client pointed at that URL).
- `tests/agents/test_nemotron_director_agent.py` (new): constructor tests (missing key, key precedence, default/custom model name, `estimate_cost() == 0.03`); `run()` tests with a mocked `client.chat.completions.parse` — LLM's own decision honored when under the retry cap; forced `"reject"` when `retry_count >= max_retries` regardless of a faked `"regenerate"`/`"accept"` verdict, with `feedback` still coming from the (faked) LLM response; `temperature=1.0`/`top_p=0.95` passed through; SDK exception and unparseable-response wrapped as `DirectorAgentError`.
- `tests/agents/test_director_agent.py` (existing, stub): add `estimate_cost() == 0.0`.
- `tests/agents/test_protocols.py` (existing): add `DirectorAgentProtocol` conformance for both `DirectorAgent` and `NemotronDirectorAgent`.
- `tests/test_orchestrator.py` (existing): `director_agent` injectable with stub fallback preserved; fresh-per-retry-attempt budget guard test for `director_agent` (counting fake director, budget sized to allow only some attempts, same pattern as the existing `image_agent`/`review_agent` tests); one real-`NemotronDirectorAgent`-with-mocked-client smoke test through the orchestrator end-to-end.
- `tests/agents/test_factory.py` (existing): add `nemotron_api_key`/`nemotron_client` threading test for `director_agent`; update the "exactly the expected keys" test to 6 keys; update the end-to-end integration test to also mock a Nemotron-style `chat.completions.parse` call so the full `run_pipeline(**build_real_agents(...))` path (now including real director) still runs fully offline.

No live-API tests, consistent with every other spec in this project — no real Elice keys exist in this environment yet.

## Open questions / follow-ups (not blocking this spec)

- Real `base_url` values are still unknown (Elice's docs use placeholders throughout; only `gpt-image-2`'s was incidentally not redacted). Once real keys/endpoints are issued, the per-stage env vars (`OPENAI_PLANNING_BASE_URL`, etc.) need to be set in the actual deployment environment — no code change required, per this spec's design.
- Whether several stages genuinely share one Elice gateway URL (making some of the 6 `base_url` env vars redundant in practice) can only be confirmed once real endpoint values are in hand.
- The "edit vs. regenerate" decision actually changing orchestrator behavior, and wiring `DirectorDecision.feedback`/a possible future edit-vs-regenerate signal into a real retry path — deferred to a future spec, same as noted in the `ReviewAgent` spec.
- `VideoRenderAgent`/`VeoBackend` remain fully stubbed, unrelated to this spec.
