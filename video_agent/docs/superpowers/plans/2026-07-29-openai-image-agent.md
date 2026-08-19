# OpenAIImageAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a real `OpenAIImageAgent` that turns `Prompts` into a `Candidate` via OpenAI's image-generation API, coexisting with (not replacing) the existing stub `ImageAgent`.

**Architecture:** One new file, `src/video_draft_pipeline/agents/openai_image_agent.py`, exposing `.run(prompts) -> Candidate`, matching the stub's shape. `OpenAIImageAgent` subclasses `BaseOpenAIAgent` for constructor/key-resolution/client-injection reuse only — it does not use `_structured_completion` (that helper is built around `chat.completions.parse`/`response_format`, which the Images API doesn't have). `run()` calls `self._client.images.generate(...)`, decodes the base64 image the API returns, writes it to a local file under `output_dir`, and returns a `Candidate` whose `image_url` is that file's path.

**Tech Stack:** Python 3.11+, Pydantic v2, `openai` Python SDK (already a runtime dependency), pytest + `unittest.mock`, stdlib `base64`/`pathlib`/`uuid`.

## Global Constraints

- The existing stub `src/video_draft_pipeline/agents/image_agent.py` and its tests (`tests/agents/test_image_agent.py`) are not modified.
- `OpenAIImageAgent` subclasses `BaseOpenAIAgent` (`from .openai_agent_base import BaseOpenAIAgent`) and sets `error_cls = ImageAgentError`. `MissingAPIKeyError` is inherited behavior from `BaseOpenAIAgent.__init__`, not redefined or re-imported by name in this agent's own code.
- No `response_format` parameter is passed to `images.generate` — current `gpt-image-1`-family models always return `b64_json` and don't accept that parameter; `gpt-image-2` is assumed to keep the same contract per its documented usage.
- `IMAGE_SIZE = "1536x1024"` is a fixed class-level constant. No per-call or per-project size/aspect-ratio parameter in this plan — that's out of scope (see the spec's Non-goals).
- No task may make a real network call or require a real API key. All tests mock the OpenAI SDK client boundary (`client.images.generate`).
- Every test must avoid writing files outside a `tmp_path`-controlled directory: pass an explicit `output_dir=tmp_path / "media"` (or similar) to the constructor in every test except the one test that specifically verifies the `"media"` default, which must use `monkeypatch.chdir(tmp_path)` first so the default-relative directory it creates lands inside `tmp_path`, not the repo.
- `run_pipeline`/`orchestrator.py` wiring is out of scope (non-goal in the spec, `docs/superpowers/specs/2026-07-29-openai-image-agent-design.md`).
- The existing 119 tests must continue to pass unchanged after every task.

---

### Task 1: Exceptions and fail-fast constructor (with local output directory setup)

**Files:**
- Create: `src/video_draft_pipeline/agents/openai_image_agent.py`
- Test: `tests/agents/test_openai_image_agent.py`

**Interfaces:**
- Consumes: `video_draft_pipeline.agents.openai_agent_base.BaseOpenAIAgent` (existing — `__init__(self, model_name, api_key=None, client=None)`, raises `MissingAPIKeyError`), `video_draft_pipeline.agents.openai_agent_base.MissingAPIKeyError` (existing, for tests).
- Produces:
  - `class ImageAgentError(Exception)`
  - `class OpenAIImageAgent(BaseOpenAIAgent)` with `error_cls = ImageAgentError`, `IMAGE_SIZE = "1536x1024"` class attribute, and `__init__(self, model_name: str = "gpt-image-2", output_dir: str | Path = "media", api_key: str | None = None, client: "OpenAI | None" = None)` — delegates to `super().__init__(model_name, api_key, client)`, then sets `self.output_dir = Path(output_dir)` and creates it (`mkdir(parents=True, exist_ok=True)`).

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_openai_image_agent.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.agents.openai_image_agent import OpenAIImageAgent


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        OpenAIImageAgent(output_dir=tmp_path / "media")


def test_explicit_api_key_takes_precedence_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIImageAgent(
        api_key="explicit-key", client=MagicMock(), output_dir=tmp_path / "media"
    )

    assert agent.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.api_key == "env-key"


def test_default_model_name_is_gpt_image_2(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIImageAgent(client=MagicMock(), output_dir=tmp_path / "media")

    assert agent.model_name == "gpt-image-2"


def test_custom_model_name_stored(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    agent = OpenAIImageAgent(
        model_name="custom-imager", client=MagicMock(), output_dir=tmp_path / "media"
    )

    assert agent.model_name == "custom-imager"


def test_output_dir_created_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    nested = tmp_path / "nested" / "media"
    assert not nested.exists()

    OpenAIImageAgent(client=MagicMock(), output_dir=nested)

    assert nested.is_dir()


def test_default_output_dir_is_media(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.chdir(tmp_path)

    agent = OpenAIImageAgent(client=MagicMock())

    assert agent.output_dir == Path("media")
    assert (tmp_path / "media").is_dir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_image_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_draft_pipeline.agents.openai_image_agent'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/video_draft_pipeline/agents/openai_image_agent.py`:

```python
from pathlib import Path

from openai import OpenAI

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_image_agent.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (119 existing + 7 new = 126 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_image_agent.py tests/agents/test_openai_image_agent.py
git commit -m "feat: add OpenAIImageAgent with fail-fast key resolution and output-dir setup"
```

---

### Task 2: `run()` — image generation, local storage, and error handling

**Files:**
- Modify: `src/video_draft_pipeline/agents/openai_image_agent.py`
- Test: `tests/agents/test_openai_image_agent.py`

**Interfaces:**
- Consumes: `self.model_name`, `self._client`, `self.output_dir`, `self.IMAGE_SIZE`, `self.error_cls` (all Task 1), `video_draft_pipeline.schema.Prompts` (existing — `.image_prompt: str`), `video_draft_pipeline.schema.Candidate` (existing — `candidate_id: str`, `image_url: str`, `generated_by: str`).
- Produces: `OpenAIImageAgent.run(self, prompts: Prompts) -> Candidate`. Raises `ImageAgentError` if the SDK call fails or the response has no usable image data.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agents/test_openai_image_agent.py`:

```python
from types import SimpleNamespace

from video_draft_pipeline.agents.openai_image_agent import ImageAgentError
from video_draft_pipeline.schema import Prompts


def _fake_image_response(b64_json="ZmFrZS1pbWFnZS1ieXRlcw=="):
    image = SimpleNamespace(b64_json=b64_json)
    return SimpleNamespace(data=[image])


def test_run_calls_sdk_with_expected_model_and_size(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.images.generate.return_value = _fake_image_response()
    agent = OpenAIImageAgent(
        model_name="custom-imager", client=client, output_dir=tmp_path / "media"
    )
    prompts = Prompts(image_prompt="a castle at night", video_motion_prompt="pan left")

    agent.run(prompts)

    _, kwargs = client.images.generate.call_args
    assert kwargs["model"] == "custom-imager"
    assert kwargs["prompt"] == "a castle at night"
    assert kwargs["size"] == "1536x1024"


def test_run_writes_decoded_image_to_output_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.images.generate.return_value = _fake_image_response()
    output_dir = tmp_path / "media"
    agent = OpenAIImageAgent(client=client, output_dir=output_dir)
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")

    candidate = agent.run(prompts)

    file_path = Path(candidate.image_url)
    assert file_path.exists()
    assert file_path.read_bytes() == b"fake-image-bytes"


def test_run_returns_candidate_with_file_path_as_image_url(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.images.generate.return_value = _fake_image_response()
    output_dir = tmp_path / "media"
    agent = OpenAIImageAgent(
        model_name="custom-imager", client=client, output_dir=output_dir
    )
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")

    candidate = agent.run(prompts)

    assert candidate.generated_by == "custom-imager"
    assert candidate.candidate_id.startswith("cand_")
    assert candidate.image_url == str(output_dir / f"{candidate.candidate_id}.png")


def test_run_generates_unique_candidate_ids(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.images.generate.return_value = _fake_image_response()
    agent = OpenAIImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")

    c1 = agent.run(prompts)
    c2 = agent.run(prompts)

    assert c1.candidate_id != c2.candidate_id


def test_run_raises_on_empty_data(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.images.generate.return_value = SimpleNamespace(data=[])
    agent = OpenAIImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")

    with pytest.raises(ImageAgentError):
        agent.run(prompts)


def test_run_raises_on_missing_b64_json(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.images.generate.return_value = _fake_image_response(b64_json=None)
    agent = OpenAIImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")

    with pytest.raises(ImageAgentError):
        agent.run(prompts)


def test_run_wraps_sdk_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    client = MagicMock()
    client.images.generate.side_effect = RuntimeError("boom")
    agent = OpenAIImageAgent(client=client, output_dir=tmp_path / "media")
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")

    with pytest.raises(ImageAgentError):
        agent.run(prompts)
```

(`ZmFrZS1pbWFnZS1ieXRlcw==` is the base64 encoding of the literal bytes `fake-image-bytes` — verified via `base64.b64encode(b"fake-image-bytes")`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_openai_image_agent.py -v -k test_run_`
Expected: FAIL with `AttributeError: 'OpenAIImageAgent' object has no attribute 'run'`

- [ ] **Step 3: Write the minimal implementation**

In `src/video_draft_pipeline/agents/openai_image_agent.py`, change the top imports:

```python
from pathlib import Path

from openai import OpenAI

from .openai_agent_base import BaseOpenAIAgent
```

to:

```python
import base64
import uuid
from pathlib import Path

from openai import OpenAI

from ..schema import Candidate, Prompts
from .openai_agent_base import BaseOpenAIAgent
```

Then add a `run` method to `OpenAIImageAgent` (after `__init__`):

```python
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_openai_image_agent.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (119 existing + 14 new = 133 passed).

- [ ] **Step 6: Commit**

```bash
git add src/video_draft_pipeline/agents/openai_image_agent.py tests/agents/test_openai_image_agent.py
git commit -m "feat: implement OpenAIImageAgent.run with image generation and local storage"
```

---

## Self-Review Notes

- **Spec coverage:** Goals (real agent producing `Candidate` from `Prompts`, real `images.generate` call, base64 decode + local persistence, `BaseOpenAIAgent` reuse without stretching `_structured_completion`, fail-loud `ImageAgentError`, stub untouched) → Tasks 1-2. Non-goals (no orchestrator wiring, no live test, no configurable size, no `image_edit_model` usage, no shared Images-API helper in the base class) → untouched, not in any task; `IMAGE_SIZE` is a plain class constant with no override path introduced anywhere. Architecture (new file, subclass `BaseOpenAIAgent`, `error_cls`, no `response_format`) → Task 1 (class shape) and Task 2 (`run()`). Key resolution → Task 1 (inherited, verified by tests). Local image storage (`output_dir` param, `mkdir`, `<candidate_id>.png` naming, plain path string as `image_url`) → Task 1 (setup) and Task 2 (write + return). Error handling (SDK exception, empty/missing data) → Task 2. Testing (key-free, SDK-call assertions, file-write verification, unique IDs, both error branches, wrapped exception) → Tasks 1-2.
- **Placeholder scan:** no TBD/TODO markers; every step has complete, final code.
- **Type consistency:** `OpenAIImageAgent.__init__` signature in Task 1 (`model_name`, `output_dir`, `api_key`, `client`) matches every constructor call across both tasks' tests. `error_cls = ImageAgentError` (Task 1) matches `self.error_cls(...)` raises in Task 2's `run()`. `IMAGE_SIZE` class attribute (Task 1) matches `size=self.IMAGE_SIZE` in Task 2's `run()` and the `"1536x1024"` assertion in Task 2's SDK-call test. `Candidate`/`Prompts` field names (`candidate_id`, `image_url`, `generated_by`, `image_prompt`) match `schema.py`'s existing definitions exactly — confirmed against the current file, not from memory.

