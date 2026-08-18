# Real agent construction factory — design spec

## Context

Two prior branches gave `run_pipeline()` optional per-agent injection parameters (`planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`) and budget tracking for whatever real agent is injected. Both branches' final reviews flagged the same follow-up, left out of scope each time: actually constructing the 4 real agents to inject requires knowing 4 separate module paths (`agents.openai_planning_agent`, `agents.openai_storyboard_agent`, `agents.openai_prompt_agent`, `agents.openai_image_agent`) and 2 different constructor shapes — `OpenAIImageAgent(model_name, output_dir, api_key, client)` versus the other three's `(model_name, api_key, client)`. Nothing in the codebase ties this together; a caller has to read 4 files to wire up real agents at all.

## Goals

- One function call that constructs all 4 real agents with shared configuration (API key, model names, image output directory) and returns them ready to hand to `run_pipeline`.
- The call composes directly with `run_pipeline`'s existing injection parameters — no new parameter names or shapes for the caller to learn beyond the one function.
- `orchestrator.py`'s own import graph stays untouched — it must not gain a dependency on any `OpenAI*Agent` module just because this factory exists elsewhere in the package.

## Non-goals

- Constructing `ReviewAgent`, `DirectorAgent`, or `VideoRenderAgent`/`VeoBackend` — none of the 3 remaining stages have real implementations yet, so there's nothing to factory-construct for them.
- Any config file, env-var-driven auto-construction, or CLI flag for "use real agents." The caller still explicitly calls the factory and explicitly passes its output to `run_pipeline` — construction stays opt-in and explicit, matching how injection itself already works.
- Live-API or integration tests against the real OpenAI API. No key exists in this environment.
- Changing any of the 4 `OpenAI*Agent` constructors themselves. The factory adapts to their existing signatures; it doesn't reshape them.

## Design

### `build_real_agents`

New file `src/video_draft_pipeline/agents/factory.py`, kept separate from `orchestrator.py` so that `orchestrator.py`'s import graph never gains a dependency on any `OpenAI*Agent` module — injecting nothing keeps the pipeline fully offline with zero `openai`-specific imports pulled in, a property worth preserving.

```python
from pathlib import Path

from openai import OpenAI

from ..config import ModelConfig
from .openai_image_agent import OpenAIImageAgent
from .openai_planning_agent import OpenAIPlanningAgent
from .openai_prompt_agent import OpenAIPromptAgent
from .openai_storyboard_agent import OpenAIStoryboardAgent


def build_real_agents(
    api_key: str | None = None,
    output_dir: str | Path = "media",
    model_config: ModelConfig | None = None,
    client: OpenAI | None = None,
) -> dict[str, object]:
    models = model_config or ModelConfig()
    return {
        "planning_agent": OpenAIPlanningAgent(models.planning_model, api_key=api_key, client=client),
        "storyboard_agent": OpenAIStoryboardAgent(models.storyboard_model, api_key=api_key, client=client),
        "prompt_agent": OpenAIPromptAgent(models.prompt_model, api_key=api_key, client=client),
        "image_agent": OpenAIImageAgent(models.image_model, output_dir=output_dir, api_key=api_key, client=client),
    }
```

The returned dict's keys are deliberately exactly `run_pipeline`'s 4 injection parameter names, so the intended usage is direct unpacking:

```python
from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.orchestrator import run_pipeline

run_pipeline(project_input, **build_real_agents(api_key="sk-..."))
```

One call replaces needing to know 4 module paths and 2 differing constructor shapes.

`model_config` reuses the existing `config.ModelConfig` dataclass — the same one `run_pipeline` already uses to pick model names for stub construction — rather than introducing a second, parallel configuration concept. `client` is threaded through to all 4 constructors for test injection, mirroring the `client=MagicMock()` pattern every existing `OpenAI*Agent` test already uses; this is what makes the factory itself testable with zero network calls.

Fail-fast behavior is inherited for free: each `OpenAI*Agent.__init__` already raises `MissingAPIKeyError` if no key resolves (explicit `api_key` or `OPENAI_API_KEY` env var), so `build_real_agents()` with no key available fails immediately on the first agent it constructs (`OpenAIPlanningAgent`), before constructing the rest.

## Testing

New `tests/agents/test_factory.py`:

- Calling `build_real_agents()` with no `api_key` and no `OPENAI_API_KEY` env var raises `MissingAPIKeyError`.
- An explicit `api_key` is threaded through to all 4 returned agents (construct with `client=MagicMock()`, assert `.api_key` on each of the 4 dict values).
- The returned dict has exactly the 4 keys `run_pipeline` expects: `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent` — no more, no fewer.
- A custom `ModelConfig` is respected: each returned agent's `model_name` matches the corresponding `ModelConfig` field (`planning_model`, `storyboard_model`, `prompt_model`, `image_model`).
- A custom `output_dir` is threaded through to the image agent only (the other 3 constructors don't take one).
- One integration-style test: `run_pipeline(project_input, **build_real_agents(api_key="test-key", client=shared_mock))` completes successfully end-to-end. A single shared `MagicMock` client can have both `client.chat.completions.parse.return_value` and `client.images.generate.return_value` configured at once (different attribute paths on the same mock object), so this proves the factory's output is directly usable by `run_pipeline`, fully offline — closing the loop the spec exists to close.

No live-API test, consistent with every other spec in this project.

## Open questions / follow-ups (not blocking this spec)

- If `ReviewAgent`/`DirectorAgent`/`VideoRenderAgent` ever get real implementations and become injectable (as flagged as a follow-up in the budget-tracking branch's final review), this factory should grow to cover them the same way — not a new, separate mechanism.
