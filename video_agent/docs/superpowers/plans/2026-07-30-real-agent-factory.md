# Real Agent Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `build_real_agents()`, a small factory that constructs all 4 real OpenAI-backed agents with shared configuration and returns them keyed exactly for `**`-unpacking into `run_pipeline`'s injection parameters — closing the agent-construction ergonomics gap flagged in the last two branches' final reviews.

**Architecture:** One new function in a new file, `agents/factory.py`, kept separate from `orchestrator.py` so the orchestrator's import graph never gains a dependency on any `OpenAI*Agent` module. The function takes shared config (`api_key`, `output_dir`, `model_config`, `client`) and returns a `dict[str, object]` whose keys are `run_pipeline`'s 4 injection parameter names.

**Tech Stack:** Python 3.11+, Pydantic v2, `unittest.mock.MagicMock`, pytest.

## Global Constraints

- `orchestrator.py` must not import anything from `factory.py` or any `OpenAI*Agent` module. This plan does not modify `orchestrator.py` at all.
- The returned dict's keys must be exactly `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent` — matching `run_pipeline`'s parameter names exactly, so `run_pipeline(project_input, **build_real_agents(...))` works.
- `model_config` reuses the existing `config.ModelConfig` dataclass — no new config type.
- `client` is threaded through to all 4 constructors, enabling fully offline testing via `MagicMock()`.
- No live-API or integration tests against the real OpenAI API. No new dependencies.

---

### Task 1: `build_real_agents()` factory function

**Files:**
- Create: `src/video_draft_pipeline/agents/factory.py`
- Test: `tests/agents/test_factory.py`

**Interfaces:**
- Consumes: `OpenAIPlanningAgent(model_name, api_key, client)`, `OpenAIStoryboardAgent(model_name, api_key, client)`, `OpenAIPromptAgent(model_name, api_key, client)`, `OpenAIImageAgent(model_name, output_dir, api_key, client)` (all already exist, unchanged), `ModelConfig` (from `src/video_draft_pipeline/config.py`, fields `planning_model`, `storyboard_model`, `prompt_model`, `image_model`), `MissingAPIKeyError` (from `src/video_draft_pipeline/agents/openai_agent_base.py`).
- Produces: `build_real_agents(api_key: str | None = None, output_dir: str | Path = "media", model_config: ModelConfig | None = None, client: OpenAI | None = None) -> dict[str, object]` in `video_draft_pipeline.agents.factory`. No other task in this plan consumes it — this is a standalone, self-contained deliverable.

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_factory.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.agents.openai_storyboard_agent import SceneDraft, StoryboardDraft
from video_draft_pipeline.config import ModelConfig
from video_draft_pipeline.orchestrator import run_pipeline
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput, Prompts


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        build_real_agents(output_dir=tmp_path / "media")


def test_explicit_api_key_threaded_to_all_agents(tmp_path):
    agents = build_real_agents(
        api_key="explicit-key", client=MagicMock(), output_dir=tmp_path / "media"
    )

    assert agents["planning_agent"].api_key == "explicit-key"
    assert agents["storyboard_agent"].api_key == "explicit-key"
    assert agents["prompt_agent"].api_key == "explicit-key"
    assert agents["image_agent"].api_key == "explicit-key"


def test_returns_exactly_the_four_expected_keys(tmp_path):
    agents = build_real_agents(
        api_key="explicit-key", client=MagicMock(), output_dir=tmp_path / "media"
    )

    assert set(agents.keys()) == {
        "planning_agent",
        "storyboard_agent",
        "prompt_agent",
        "image_agent",
    }


def test_custom_model_config_threaded_to_each_agent(tmp_path):
    model_config = ModelConfig(
        planning_model="custom-planner",
        storyboard_model="custom-storyboarder",
        prompt_model="custom-prompter",
        image_model="custom-imager",
    )

    agents = build_real_agents(
        api_key="explicit-key",
        client=MagicMock(),
        output_dir=tmp_path / "media",
        model_config=model_config,
    )

    assert agents["planning_agent"].model_name == "custom-planner"
    assert agents["storyboard_agent"].model_name == "custom-storyboarder"
    assert agents["prompt_agent"].model_name == "custom-prompter"
    assert agents["image_agent"].model_name == "custom-imager"


def test_output_dir_threaded_to_image_agent_only(tmp_path):
    custom_dir = tmp_path / "custom-media"

    agents = build_real_agents(
        api_key="explicit-key", client=MagicMock(), output_dir=custom_dir
    )

    assert agents["image_agent"].output_dir == custom_dir
    assert custom_dir.is_dir()


def test_build_real_agents_output_works_with_run_pipeline(tmp_path):
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )
    draft = StoryboardDraft(
        scenes=[
            SceneDraft(
                beat_id=beat_id,
                camera="cam",
                subject="subj",
                action="act",
                setting="set",
                required_elements=[],
                duration_weight=1,
            )
            for beat_id in ("setup", "conflict", "climax", "resolution")
        ]
    )
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")

    def fake_parse(*, model, messages, response_format):
        if response_format is Narrative:
            parsed = narrative
        elif response_format is StoryboardDraft:
            parsed = draft
        elif response_format is Prompts:
            parsed = prompts
        else:
            raise AssertionError(f"unexpected response_format: {response_format}")
        message = SimpleNamespace(parsed=parsed, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    shared_client = MagicMock()
    shared_client.chat.completions.parse.side_effect = fake_parse
    image_data = SimpleNamespace(b64_json="ZmFrZS1pbWFnZS1ieXRlcw==")
    shared_client.images.generate.return_value = SimpleNamespace(data=[image_data])

    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event"
    )

    project = run_pipeline(
        project_input,
        **build_real_agents(
            api_key="test-key", client=shared_client, output_dir=tmp_path / "media"
        ),
    )

    assert len(project.scenes) == 4
    assert project.scenes[0].render is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_factory.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.factory'`.

- [ ] **Step 3: Write the implementation**

Create `src/video_draft_pipeline/agents/factory.py`:

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_factory.py -v`

Expected: PASS (6 passed).

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest -v`

Expected: all tests pass, zero failures (previous total was 158; this plan adds 6 tests, so expect 164 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/factory.py tests/agents/test_factory.py
git commit -m "feat: add build_real_agents() factory for run_pipeline injection"
```

---

## Self-Review Notes

- **Spec coverage:** `build_real_agents()` signature, return-dict shape matching `run_pipeline`'s param names, `ModelConfig` reuse, `client` pass-through, fail-fast key resolution, and separate-file placement (no `orchestrator.py` import) — all covered by Task 1's single implementation step. Testing section's 6 scenarios (missing key, explicit key threading, exact dict keys, custom `ModelConfig`, `output_dir` threading, end-to-end with `run_pipeline`) map 1:1 to Task 1's 6 tests. Non-goals (no `ReviewAgent`/`DirectorAgent`/`VideoRenderAgent` construction, no config-file/env-driven auto-construction, no live-API test, no changes to the 4 `OpenAI*Agent` constructors) — nothing in this plan touches any of them.
- **Placeholder scan:** no TBD/TODO; every step has complete, runnable code, including the full `fake_parse` side-effect function for the integration test rather than a stubbed-out version.
- **Type consistency:** `build_real_agents`'s signature and returned dict keys match exactly what the design spec's usage example expects (`run_pipeline(project_input, **build_real_agents(...))`); the 4 constructor calls use the exact parameter names and positions each `OpenAI*Agent.__init__` already defines (verified against `agents/openai_planning_agent.py`, `openai_storyboard_agent.py`, `openai_prompt_agent.py`, `openai_image_agent.py`).
