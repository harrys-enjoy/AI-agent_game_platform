# Gemini unification — replacing Elice-proxied agents with direct Gemini — design spec

## Context

Five of the pipeline's seven stages (`planning`, `storyboard`, `prompt`, `image`, `director`) currently route through 엘리스(Elice)'s OpenAI-compatible proxy, using OpenAI/NVIDIA model strings Elice hasn't fully provisioned yet — as of 2026-08-01 the user still doesn't have working Elice keys for these. Two stages (`review`, `image_edit`) already call Gemini directly with the user's own `GEMINI_API_KEY` (Google AI Studio), bypassing Elice entirely, and both render backends (`VeoBackend`, `LTXBackend`) are likewise already real and direct.

The user's mentor suggested a fallback: if Elice access keeps stalling, stop waiting and unify the whole pipeline onto direct Gemini calls, since Gemini already works for two stages and is cost-efficient. This spec designs that fallback as a real, working alternative — built on an isolated git branch (`gemini-unification`) so `master` (Elice-backed, the current working default) is untouched unless/until the user deliberately decides to merge.

Real Gemini 3 model documentation was pasted directly from Google's own docs (overview page, per-model capability cards, Interactions API usage, image-generation/editing guide, pricing sheet). Two things confirmed from it:

1. `BaseGeminiAgent._structured_interaction` (`agents/gemini_agent_base.py:34`) passes `model_name` straight through to `interactions.create(model=...)` with no prefix handling. The existing `"google/"` prefix on `image_edit_model`'s default (`"google/gemini-2.5-flash-image"`) and `review_model`'s default (`"google/gemini-3-pro-image-preview"`) is Elice's proxy-routing convention, not a real Google model ID — a latent bug that's never been caught because neither agent has been called with a real client yet. This spec uses bare model IDs throughout and fixes both existing defaults as part of the same pass.
2. The *current* `review_model` default, `gemini-3-pro-image-preview`, is an image-generation model. Its own capability card states "Structured outputs: Not supported" — meaning `ReviewAgent`'s existing default model can't actually do what `GeminiReviewAgent.run()` asks of it (a schema-validated JSON verdict). This was already broken, never exercised against a real endpoint. This spec's `review_model` change to `gemini-3.6-flash` (which does support structured output) is a correctness fix, not just a swap.

## Goals

- A `gemini-unification` git branch where `build_real_agents()` constructs all 7 injectable agents backed by direct Gemini calls (`GEMINI_API_KEY`, no Elice proxy), as a genuine working alternative to today's Elice-backed default.
- Five new agent classes (`GeminiPlanningAgent`, `GeminiStoryboardAgent`, `GeminiPromptAgent`, `GeminiImageAgent`, `GeminiDirectorAgent`), each a drop-in replacement conforming to the exact same `Protocol` its Elice-backed sibling already implements — zero changes to `protocols.py`, `orchestrator.py`, or any schema.
- `GeminiReviewAgent`/`GeminiImageEditAgent` repointed to corrected bare model IDs (`gemini-3.6-flash`, `gemini-3-pro-image` respectively) on this branch.
- `ModelConfig`/`ApiKeys`/`.env.example`/README updated to reflect an all-Gemini, no-Elice-proxy configuration.
- All new agents fully unit-tested with mocked clients, matching this project's existing convention — no live API calls in the test suite.

## Non-goals

- Actually cutting `master` over. This branch is a prepared, working alternative — the decision to merge is separate and not part of this spec.
- Merging `ReviewAgent` and `DirectorAgent` into a single call, despite Google's own suggested pipeline sheet recommending it. Explicit user decision: keep them as two separate calls (same model, `gemini-3.6-flash`) to avoid touching the orchestrator's data flow or either agent's schema.
- Any change to `VeoBackend`/`LTXBackend` — already real and direct, unrelated to this decision.
- `thinking_level`/`generation_config` tuning per stage. Google's docs only document `thinking_level` control for `gemini-3.1-pro-preview`, `gemini-3.1-flash-lite`, and `gemini-3-flash-preview` specifically — not confirmed for `gemini-3.6-flash`, `gemini-3.5-flash-lite`, or the image models used here. Left at model defaults; a follow-up once real usage data exists.
- Temperature tuning. Google explicitly recommends leaving temperature at its default (1.0) for all Gemini 3 models — no agent in this spec sets it.

## Design

### Model mapping

| Stage | Class | Model ID | Source |
|---|---|---|---|
| planning | `GeminiPlanningAgent` | `gemini-3.1-pro-preview` | only ID shown in real code samples; no stable non-preview card provided |
| storyboard | `GeminiStoryboardAgent` | `gemini-3.6-flash` | stable model card, structured outputs supported |
| prompt | `GeminiPromptAgent` | `gemini-3.5-flash-lite` | stable model card, structured outputs supported |
| image (drafts) | `GeminiImageAgent` | `gemini-3.1-flash-image` | stable model card ("Nano Banana 2") |
| review | `GeminiReviewAgent` (existing) | `gemini-3.6-flash` | was `gemini-3-pro-image-preview`, corrected — see Context |
| director | `GeminiDirectorAgent` | `gemini-3.6-flash` | text-only, structured outputs |
| image_edit (targeted fixes) | `GeminiImageEditAgent` (existing) | `gemini-3-pro-image` | stable model card ("Nano Banana Pro") — pricier/higher-quality tier reserved for feedback-driven edits, cheap tier for bulk drafts |

No `google/` prefix anywhere in this table — all bare IDs, matching real Google AI Studio usage (confirmed directly from the pasted docs' code samples).

### Text-only agents build a single `input` string, not a messages list

Gemini's Interactions API has no OpenAI-style `messages` list with `system`/`user` roles — `interactions.create(model=..., input=...)` takes either a plain string or a list of content blocks (`_structured_interaction` already expects `list[dict]`). Each new text-only agent (`GeminiPlanningAgent`, `GeminiStoryboardAgent`, `GeminiPromptAgent`, `GeminiDirectorAgent`) combines what were previously separate `system`/`user` message strings into one prompt, passed as `[{"type": "text", "text": combined_prompt}]`. This is the only structural difference from the OpenAI-family siblings being replaced — everything else (schema, validation, business logic) is carried over unchanged.

`GeminiPlanningAgent` (`agents/gemini_planning_agent.py`), replacing `OpenAIPlanningAgent`:

```python
from ..schema import Narrative, ProjectInput
from .gemini_agent_base import BaseGeminiAgent


def _build_input(project_input: ProjectInput) -> str:
    requirements = ", ".join(project_input.brand_requirements) or "none"
    return (
        "You are a creative director generating a 4-beat narrative for a game "
        "marketing video draft. Produce exactly one beat for each of: "
        "setup, conflict, climax, resolution.\n\n"
        f"Preset: {project_input.preset}\n"
        f"Scene type: {project_input.scene_type}\n"
        f"Brief: {project_input.brief}\n"
        f"Brand requirements: {requirements}"
    )


class PlanningAgentError(Exception):
    pass


class GeminiPlanningAgent(BaseGeminiAgent):
    error_cls = PlanningAgentError
    ESTIMATED_COST_USD = 0.01
    base_url_config_field = None

    def __init__(self, model_name: str = "gemini-3.1-pro-preview", api_key: str | None = None, client=None, base_url: str | None = None):
        super().__init__(model_name, api_key, client, base_url)

    def run(self, project_input: ProjectInput) -> Narrative:
        input_content = [{"type": "text", "text": _build_input(project_input)}]
        return self._structured_interaction(input_content, Narrative)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

`GeminiStoryboardAgent` (`agents/gemini_storyboard_agent.py`), replacing `OpenAIStoryboardAgent`: identical logic to today's `_drafts_to_scenes`/`SceneDraft`/`StoryboardDraft`/beat-order-and-duration-weight validation (`agents/openai_storyboard_agent.py:36-124`), only the message-building and the `_structured_completion`→`_structured_interaction` call swapped. Model `gemini-3.6-flash`.

`GeminiPromptAgent` (`agents/gemini_prompt_agent.py`), replacing `OpenAIPromptAgent`: identical `feedback`-appending logic and `required_elements` post-processing (`agents/openai_prompt_agent.py:23-27,55-56`), same swap. Model `gemini-3.5-flash-lite`.

`GeminiDirectorAgent` (`agents/gemini_director_agent.py`), replacing `NemotronDirectorAgent`: identical `DirectorVerdict` schema and the locked-in "always call the LLM, force `reject` once `scene.retry_count >= scene.max_retries`" behavior (`agents/nemotron_director_agent.py:56-71`) — this safety invariant carries over unchanged regardless of provider. No `extra_body`/`reasoning_budget`/`max_tokens` tuning (that was Nemotron-specific per Elice's docs); Gemini 3's structured-output + default `thinking_level: high` is used as-is. Model `gemini-3.6-flash`. Text-only — `DirectorAgent` never receives the candidate image, only `review: ConsistencyReview` (text), so no image content block is needed despite `gemini-3.6-flash` being multimodal-capable.

`GeminiImageAgent` (`agents/gemini_image_agent.py`), replacing `OpenAIImageAgent`: mirrors `GeminiImageEditAgent`'s existing image-call pattern (`agents/gemini_image_edit_agent.py`) minus the image-input content block — text-only prompt in, `interaction.output_image.data` (base64) out, written to `output_dir/{candidate_id}.png`:

```python
import base64
import uuid
from pathlib import Path

from ..schema import Candidate, Prompts
from .gemini_agent_base import BaseGeminiAgent


class ImageAgentError(Exception):
    pass


class GeminiImageAgent(BaseGeminiAgent):
    error_cls = ImageAgentError
    ESTIMATED_COST_USD = 0.039
    base_url_config_field = None

    def __init__(self, model_name: str = "gemini-3.1-flash-image", output_dir: str | Path = "media", api_key: str | None = None, client=None, base_url: str | None = None):
        super().__init__(model_name, api_key, client, base_url)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, prompts: Prompts) -> Candidate:
        input_content = [{"type": "text", "text": prompts.image_prompt}]
        try:
            interaction = self._client.interactions.create(model=self.model_name, input=input_content)
        except Exception as exc:
            raise self.error_cls(f"Gemini image call failed: {exc}") from exc
        if interaction.output_image is None:
            raise self.error_cls("Gemini image call returned no output image")

        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        image_bytes = base64.b64decode(interaction.output_image.data)
        file_path = self.output_dir / f"{candidate_id}.png"
        file_path.write_bytes(image_bytes)

        return Candidate(candidate_id=candidate_id, image_url=str(file_path), generated_by=self.model_name)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
```

`ESTIMATED_COST_USD = 0.039` and `GeminiImageEditAgent`'s new `ESTIMATED_COST_USD = 0.134` (up from `0.039`, reflecting the `gemini-3-pro-image` upgrade) both come from Google's own recommended-pipeline pricing sheet the user pasted, not a guess.

### `GeminiReviewAgent`/`GeminiImageEditAgent` corrections (existing files)

Both get their default `model_name` corrected from the stale `google/`-prefixed strings to bare IDs, and `GeminiReviewAgent`'s default changes model entirely (image model → `gemini-3.6-flash`, a text/structured-output model — this is the fix described in Context, not a rename). No changes to either agent's `run()` logic, request shape, or schema.

### Config layer

`ModelConfig` defaults on this branch:

```python
@dataclass
class ModelConfig:
    planning_model: str = "gemini-3.1-pro-preview"
    storyboard_model: str = "gemini-3.6-flash"
    prompt_model: str = "gemini-3.5-flash-lite"
    image_model: str = "gemini-3.1-flash-image"
    image_edit_model: str = "gemini-3-pro-image"
    review_model: str = "gemini-3.6-flash"
    director_model: str = "gemini-3.6-flash"
    render_backend: str = "veo-3.1-fast"
```

`ApiKeys` drops `openai_api_key`, `nemotron_api_key`, and the five Elice `*_base_url` fields (`planning_base_url`, `storyboard_base_url`, `prompt_base_url`, `image_base_url`, `director_base_url`) — dead weight once nothing routes through Elice. `image_edit_base_url`/`review_base_url` are also dropped (both agents' `base_url_config_field` becomes `None`, matching every other Gemini agent in this design — none of them need a configurable base URL since there's no Elice gateway to point at). `gemini_api_key`, `veo_api_key`, `ltx_api_key` remain untouched:

```python
@dataclass
class ApiKeys:
    gemini_api_key: str | None = None
    veo_api_key: str | None = None
    ltx_api_key: str | None = None


def load_api_keys() -> ApiKeys:
    return ApiKeys(
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        veo_api_key=os.environ.get("VEO_API_KEY"),
        ltx_api_key=os.environ.get("LTX_API_KEY"),
    )
```

### Factory

`build_real_agents()` signature shrinks — no more `openai_api_key`/`nemotron_api_key`/`openai_client`/`nemotron_client`, since every agent now resolves through the same `gemini_api_key`/`gemini_client`:

```python
def build_real_agents(
    gemini_api_key: str | None = None,
    output_dir: str | Path = "media",
    model_config: ModelConfig | None = None,
    gemini_client: genai.Client | None = None,
) -> dict[str, object]:
    models = model_config or ModelConfig()
    return {
        "planning_agent": GeminiPlanningAgent(models.planning_model, api_key=gemini_api_key, client=gemini_client),
        "storyboard_agent": GeminiStoryboardAgent(models.storyboard_model, api_key=gemini_api_key, client=gemini_client),
        "prompt_agent": GeminiPromptAgent(models.prompt_model, api_key=gemini_api_key, client=gemini_client),
        "image_agent": GeminiImageAgent(models.image_model, output_dir=output_dir, api_key=gemini_api_key, client=gemini_client),
        "review_agent": GeminiReviewAgent(models.review_model, api_key=gemini_api_key, client=gemini_client),
        "director_agent": GeminiDirectorAgent(models.director_model, api_key=gemini_api_key, client=gemini_client),
        "image_edit_agent": GeminiImageEditAgent(models.image_edit_model, output_dir=output_dir, api_key=gemini_api_key, client=gemini_client),
    }
```

`orchestrator.run_pipeline`'s injection-parameter signatures (`planning_agent: PlanningAgentProtocol | None = None`, etc.) are untouched — every new class satisfies the existing `Protocol` its predecessor did, so no orchestrator change is needed at all.

### README / `.env.example`

README's "Real agent injection" and env var sections rewritten for this branch to describe an all-Gemini setup: one `GEMINI_API_KEY` (plus `VEO_API_KEY`/`LTX_API_KEY` for rendering, unchanged), no Elice `base_url` env vars. `.env.example` drops `OPENAI_API_KEY`, `NEMOTRON_API_KEY`, and the five `*_BASE_URL` vars this branch no longer uses.

## Testing

- Five new test files (`tests/agents/test_gemini_planning_agent.py`, `test_gemini_storyboard_agent.py`, `test_gemini_prompt_agent.py`, `test_gemini_image_agent.py`, `test_gemini_director_agent.py`), each mirroring its Elice-backed sibling's existing test suite one-for-one (constructor/key-resolution tests, `run()` happy path via a mocked `client.interactions.create`, error wrapping, `estimate_cost()`), swapped to mock the Gemini interaction shape instead of OpenAI's `chat.completions.parse`.
- `tests/agents/test_gemini_review_agent.py`/`test_gemini_image_edit_agent.py` (existing): update default-model-name assertions to the corrected bare IDs.
- `tests/agents/test_protocols.py` (existing): add conformance checks for all 5 new classes against their existing protocols — no new protocols needed.
- `tests/test_config.py`: remove coverage for dropped `ApiKeys` fields, confirm the three retained ones.
- `tests/agents/test_factory.py`: rewritten for the new `build_real_agents()` signature — exactly 7 keys, all Gemini-backed, one end-to-end `run_pipeline(**build_real_agents(...))` smoke test with a single mocked Gemini client covering every stage.
- `tests/test_orchestrator.py`: unaffected — injection is via `Protocol`, and no orchestrator code changes.

No live-API tests, consistent with every other spec in this project.

## Open questions / follow-ups (not blocking this spec)

- Whether `gemini-3.1-pro-preview` has since stabilized to a non-preview `gemini-3.1-pro` ID — no stable model card was available when this spec was written, so the confirmed-working preview ID is used. Check before the branch is considered mergeable, since a preview model can be deprecated/changed with less notice than a stable one.
- `thinking_level` tuning per stage, once real usage/cost data exists on this branch.
- The actual merge decision (this branch → `master`) is explicitly out of scope — this spec only covers building the alternative.
