# Real VeoBackend (Veo 3.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `VeoBackend`'s stubbed `render()`/`estimate_cost()` (hardcoded `stub://veo/...` clip URLs, no real API call) with a real implementation that calls Veo 3.1 via the plain Gemini API (`google-genai`, `client.models.generate_videos`), downloads the generated clip locally, and returns real cost/status data — the last of the pipeline's 7 stages to go from stub to real.

**Architecture:** `VeoBackend` gains `api_key`/`client`/`output_dir`/`poll_interval_sec` constructor params. `tier` maps to both the real Gemini-API model ID (`veo-3.1-{lite,fast,''}-generate-preview`) and the real 720p-fixed per-second price. `render()` reads the candidate's already-generated local image file, calls `generate_videos()` with an image-to-video config (rounding `duration_sec` to Veo's allowed `{4,6,8}` set), polls the returned long-running operation until done, downloads and saves the clip locally, and returns a `RenderResult` whose `cost_usd` always matches `estimate_cost()` for the same duration. No orchestrator or factory changes are needed — `VeoBackend` was already the pipeline's unconditional default render backend before this plan.

**Tech Stack:** Python 3.11+, `google-genai>=2.15` (already a dependency, used by `GeminiReviewAgent`), `unittest.mock.MagicMock`, pytest.

## Global Constraints

- Scope is `VeoBackend` only. `SelfHostedBackend`, per-scene backend selection (Veo vs. a free diffusion model), and the LTX 2.3 model are explicitly out of scope — do not touch `render_backends/selfhosted_backend.py` or its tests.
- Resolution is fixed at 720p for all tiers in this plan — no `resolution` constructor param, no 1080p/4k support.
- Targets the plain Gemini API (`genai.Client(api_key=...)`, model IDs ending in `-generate-preview`), not Vertex AI's enterprise catalog (`-001` model IDs, GCP project/service-account auth) — do not add Vertex-style auth.
- `MissingAPIKeyError` is reused from `agents/openai_agent_base.py` — do not define a duplicate exception.
- ~~No `run_pipeline`/`build_real_agents()`/orchestrator changes~~ **AMENDED after Task 2 landed:** Task 2's implementer correctly identified that this constraint was wrong — `VeoBackend` being fail-fast (requiring `VEO_API_KEY`) while still being the orchestrator's *unconditional default* broke the project's stated "runs offline unless real agents are explicitly injected" guarantee (README line 3) for real, not just in tests: the documented CLI invocation would now crash by default. Confirmed with the human partner, who chose to reintroduce a stub/real split for the render stage, mirroring the other 6 stages, over the alternative (require `VEO_API_KEY` always). Task 3 (added below) implements this: a new `StubRenderBackend` becomes the orchestrator's default; `VeoBackend` is now injection-only, exactly like `OpenAIPlanningAgent`/`GeminiReviewAgent`/`NemotronDirectorAgent`/etc.
- No live-API or integration tests against real Veo endpoints — no real `VEO_API_KEY` exists in this environment yet, consistent with every other spec in this project.
- All existing tests must keep passing (229 as of the last branch) except where this plan explicitly updates them (the two existing `render()`-based cost-math tests in `test_veo_backend.py`, which currently construct `VeoBackend` with no key/client at all and assert on `stub://veo/...` — updating them is required, not optional, since the class's construction contract is changing).

---

### Task 1: Config layer (`config.py`)

**Files:**
- Modify: `src/video_draft_pipeline/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ApiKeys.veo_api_key: str | None = None`, read from `VEO_API_KEY` by `load_api_keys()`. Task 2 consumes `config.load_api_keys().veo_api_key` directly.

- [ ] **Step 1: Write the failing test**

In `tests/test_config.py`, change `test_load_api_keys_reads_env` to add the new field's negative case:

```python
def test_load_api_keys_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("NEMOTRON_API_KEY", raising=False)
    monkeypatch.delenv("VEO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_PLANNING_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_STORYBOARD_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_PROMPT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_REVIEW_BASE_URL", raising=False)
    monkeypatch.delenv("NEMOTRON_DIRECTOR_BASE_URL", raising=False)

    keys = load_api_keys()

    assert keys.openai_api_key == "test-openai-key"
    assert keys.gemini_api_key == "test-gemini-key"
    assert keys.nemotron_api_key is None
    assert keys.veo_api_key is None
    assert keys.planning_base_url is None
    assert keys.storyboard_base_url is None
    assert keys.prompt_base_url is None
    assert keys.image_base_url is None
    assert keys.review_base_url is None
    assert keys.director_base_url is None
```

Append a new test at the end of the file:

```python
def test_load_api_keys_reads_veo_api_key(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "test-veo-key")

    keys = load_api_keys()

    assert keys.veo_api_key == "test-veo-key"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ApiKeys` has no `veo_api_key` field yet, so both the attribute access and the new test fail.

- [ ] **Step 3: Write the implementation**

Replace `src/video_draft_pipeline/config.py` in full:

```python
import os
from dataclasses import dataclass


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


@dataclass
class ApiKeys:
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    nemotron_api_key: str | None = None
    veo_api_key: str | None = None
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
        veo_api_key=os.environ.get("VEO_API_KEY"),
        planning_base_url=os.environ.get("OPENAI_PLANNING_BASE_URL"),
        storyboard_base_url=os.environ.get("OPENAI_STORYBOARD_BASE_URL"),
        prompt_base_url=os.environ.get("OPENAI_PROMPT_BASE_URL"),
        image_base_url=os.environ.get("OPENAI_IMAGE_BASE_URL"),
        review_base_url=os.environ.get("GEMINI_REVIEW_BASE_URL"),
        director_base_url=os.environ.get("NEMOTRON_DIRECTOR_BASE_URL"),
    )
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass (230 = 229 baseline + 1 new test).

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/config.py tests/test_config.py
git commit -m "feat: add veo_api_key to ApiKeys, read from VEO_API_KEY"
```

---

### Task 2: Real `VeoBackend` implementation

**Files:**
- Modify: `src/video_draft_pipeline/render_backends/veo_backend.py`
- Modify: `tests/render_backends/test_veo_backend.py`
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `config.load_api_keys().veo_api_key` (Task 1), `MissingAPIKeyError` (from `agents/openai_agent_base.py`, already exists), `schema.Candidate`/`schema.RenderResult` (already exist, unchanged).
- Produces: `VeoBackend(tier="veo-3.1-fast", api_key=None, client=None, output_dir="media", poll_interval_sec=10.0)` with `render(candidate, motion_prompt, duration_sec) -> RenderResult` and `estimate_cost(duration_sec) -> float`, satisfying the existing `RenderBackend` protocol (`name: str`, unchanged). `orchestrator.py`'s existing `VeoBackend(tier=models.render_backend)` construction call is unaffected since all new params are optional with defaults matching current call sites.

- [ ] **Step 1: Write the failing tests**

Replace `tests/render_backends/test_veo_backend.py` in full:

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.openai_agent_base import MissingAPIKeyError
from video_draft_pipeline.render_backends.veo_backend import (
    VeoBackend,
    VeoBackendError,
    _round_to_allowed_duration,
)
from video_draft_pipeline.schema import Candidate


class _FakeVideo:
    def __init__(self, data: bytes):
        self._data = data

    def save(self, path):
        Path(path).write_bytes(self._data)


class _FakeGeneratedVideo:
    def __init__(self, video: _FakeVideo):
        self.video = video


class _FakeResponse:
    def __init__(self, generated_videos: list):
        self.generated_videos = generated_videos


class _FakeOperation:
    def __init__(self, done: bool, response=None):
        self.done = done
        self.response = response


def _candidate(image_path) -> Candidate:
    return Candidate(candidate_id="c1", image_url=str(image_path), generated_by="openai/gpt-image-2")


def _done_operation(video_bytes: bytes = b"fake-video-bytes") -> _FakeOperation:
    return _FakeOperation(
        done=True,
        response=_FakeResponse([_FakeGeneratedVideo(_FakeVideo(video_bytes))]),
    )


# --- Constructor ---


def test_veo_backend_rejects_unknown_tier():
    with pytest.raises(ValueError):
        VeoBackend(tier="veo-9000")


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("VEO_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        VeoBackend(tier="veo-3.1-fast")


def test_explicit_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier="veo-3.1-fast", api_key="explicit-key", client=MagicMock())

    assert backend.api_key == "explicit-key"


def test_env_var_key_resolved_when_no_explicit_key(monkeypatch):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier="veo-3.1-fast", client=MagicMock())

    assert backend.api_key == "env-key"


@pytest.mark.parametrize(
    "tier,expected_model_id,expected_price",
    [
        ("veo-3.1-lite", "veo-3.1-lite-generate-preview", 0.05),
        ("veo-3.1-fast", "veo-3.1-fast-generate-preview", 0.10),
        ("veo-3.1-standard", "veo-3.1-generate-preview", 0.40),
    ],
)
def test_tier_maps_to_model_id_and_price(monkeypatch, tier, expected_model_id, expected_price):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier=tier, client=MagicMock())

    assert backend.model_id == expected_model_id
    assert backend.price_per_sec_usd == expected_price


def test_output_dir_created_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    nested = tmp_path / "nested" / "media"
    assert not nested.exists()

    VeoBackend(tier="veo-3.1-fast", client=MagicMock(), output_dir=nested)

    assert nested.is_dir()


# --- Duration rounding ---


@pytest.mark.parametrize(
    "duration_sec,expected",
    [
        (0.0, 4),
        (3.9, 4),
        (4.0, 4),
        (4.9, 4),
        (5.0, 6),
        (5.1, 6),
        (6.0, 6),
        (6.9, 6),
        (7.0, 8),
        (7.1, 8),
        (8.0, 8),
        (100.0, 8),
    ],
)
def test_round_to_allowed_duration(duration_sec, expected):
    assert _round_to_allowed_duration(duration_sec) == expected


# --- render() ---


def test_render_calls_sdk_with_expected_model_image_and_config(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    result = backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    _, kwargs = client.models.generate_videos.call_args
    assert kwargs["model"] == "veo-3.1-fast-generate-preview"
    assert kwargs["prompt"] == "pan left"
    assert kwargs["config"].aspect_ratio == "16:9"
    assert kwargs["config"].duration_seconds == 6
    assert kwargs["config"].generate_audio is True
    assert result.backend == "veo-3.1-fast"
    assert result.status == "done"
    assert result.clip_url == str(tmp_path / "media" / "c1.mp4")
    assert Path(result.clip_url).read_bytes() == b"fake-video-bytes"
    assert result.cost_usd == 0.60


def test_render_lite_tier_cost_math(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-lite", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    result = backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    assert result.cost_usd == 0.30


def test_render_polls_until_operation_done(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.side_effect = [_FakeOperation(done=False), _done_operation()]

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)

    assert client.operations.get.call_count == 2


def test_render_rounds_duration_before_calling_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=7.3)

    _, kwargs = client.models.generate_videos.call_args
    assert kwargs["config"].duration_seconds == 8


def test_render_wraps_sdk_exception_from_generate_videos(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.side_effect = RuntimeError("boom")

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    with pytest.raises(VeoBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)


def test_render_raises_on_empty_generated_videos(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _FakeOperation(done=True, response=_FakeResponse([]))

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    with pytest.raises(VeoBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)


def test_render_wraps_download_or_save_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()
    client.files.download.side_effect = RuntimeError("boom")

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    with pytest.raises(VeoBackendError):
        backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=6.0)


# --- estimate_cost() ---


@pytest.mark.parametrize(
    "tier,duration_sec,expected",
    [
        ("veo-3.1-lite", 6.0, 0.30),
        ("veo-3.1-fast", 6.0, 0.60),
        ("veo-3.1-standard", 6.0, 2.40),
    ],
)
def test_estimate_cost_per_tier(monkeypatch, tier, duration_sec, expected):
    monkeypatch.setenv("VEO_API_KEY", "env-key")

    backend = VeoBackend(tier=tier, client=MagicMock())

    assert backend.estimate_cost(duration_sec) == expected


def test_estimate_cost_matches_render_reported_cost(monkeypatch, tmp_path):
    monkeypatch.setenv("VEO_API_KEY", "env-key")
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-image-bytes")

    client = MagicMock()
    client.models.generate_videos.return_value = _FakeOperation(done=False)
    client.operations.get.return_value = _done_operation()

    backend = VeoBackend(
        tier="veo-3.1-fast", client=client, output_dir=tmp_path / "media", poll_interval_sec=0
    )

    estimated = backend.estimate_cost(7.3)
    result = backend.render(_candidate(image_path), motion_prompt="pan left", duration_sec=7.3)

    assert result.cost_usd == estimated
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/render_backends/test_veo_backend.py -v`
Expected: FAIL — `VeoBackend` doesn't accept `api_key`/`client`/`output_dir`/`poll_interval_sec` yet, `_round_to_allowed_duration`/`VeoBackendError` don't exist, `render()` doesn't call any SDK methods.

- [ ] **Step 3: Write the implementation**

Replace `src/video_draft_pipeline/render_backends/veo_backend.py` in full:

```python
import time
from pathlib import Path

from google import genai
from google.genai import types

from .. import config
from ..agents.openai_agent_base import MissingAPIKeyError
from ..schema import Candidate, RenderResult

PRICE_PER_SEC_USD: dict[str, float] = {
    "veo-3.1-lite": 0.05,
    "veo-3.1-fast": 0.10,
    "veo-3.1-standard": 0.40,
}

MODEL_ID_BY_TIER: dict[str, str] = {
    "veo-3.1-lite": "veo-3.1-lite-generate-preview",
    "veo-3.1-fast": "veo-3.1-fast-generate-preview",
    "veo-3.1-standard": "veo-3.1-generate-preview",
}

ALLOWED_DURATIONS = (4, 6, 8)


def _round_to_allowed_duration(duration_sec: float) -> int:
    return min(ALLOWED_DURATIONS, key=lambda allowed: (abs(allowed - duration_sec), -allowed))


class VeoBackendError(Exception):
    pass


class VeoBackend:
    def __init__(
        self,
        tier: str = "veo-3.1-fast",
        api_key: str | None = None,
        client: genai.Client | None = None,
        output_dir: str | Path = "media",
        poll_interval_sec: float = 10.0,
    ):
        if tier not in PRICE_PER_SEC_USD:
            raise ValueError(f"Unknown Veo tier: {tier}")
        resolved_key = api_key or config.load_api_keys().veo_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No Veo API key found: pass api_key explicitly or set VEO_API_KEY."
            )
        self.tier = tier
        self.name = tier
        self.api_key = resolved_key
        self.model_id = MODEL_ID_BY_TIER[tier]
        self.price_per_sec_usd = PRICE_PER_SEC_USD[tier]
        self.poll_interval_sec = poll_interval_sec
        self._client = client or genai.Client(api_key=resolved_key)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        requested_duration = _round_to_allowed_duration(duration_sec)
        image_bytes = Path(candidate.image_url).read_bytes()

        try:
            operation = self._client.models.generate_videos(
                model=self.model_id,
                prompt=motion_prompt,
                image=types.Image.from_bytes(data=image_bytes, mime_type="image/png"),
                config=types.GenerateVideosConfig(
                    aspect_ratio="16:9",
                    duration_seconds=requested_duration,
                    generate_audio=True,
                ),
            )
            operation = self._poll_until_done(operation)
        except Exception as exc:
            raise VeoBackendError(f"Veo video generation failed: {exc}") from exc

        if not operation.response or not operation.response.generated_videos:
            raise VeoBackendError("Veo call returned no generated videos")

        generated_video = operation.response.generated_videos[0]
        clip_path = self.output_dir / f"{candidate.candidate_id}.mp4"
        try:
            self._client.files.download(file=generated_video.video)
            generated_video.video.save(str(clip_path))
        except Exception as exc:
            raise VeoBackendError(f"Failed to download/save Veo video: {exc}") from exc

        return RenderResult(
            backend=self.tier,
            status="done",
            clip_url=str(clip_path),
            cost_usd=self.estimate_cost(duration_sec),
        )

    def _poll_until_done(self, operation):
        while not operation.done:
            time.sleep(self.poll_interval_sec)
            operation = self._client.operations.get(operation)
        return operation

    def estimate_cost(self, duration_sec: float) -> float:
        requested_duration = _round_to_allowed_duration(duration_sec)
        return round(self.price_per_sec_usd * requested_duration, 2)
```

In `README.md`, replace the `## Environment variables` section's export block and the sentence right after the base_url block:

```markdown
## Environment variables

`.env` is **not** auto-loaded — there is no `python-dotenv` dependency. `config.load_api_keys()` reads `os.environ` directly, so export the keys into your shell before running:

```bash
export OPENAI_API_KEY=...      # PowerShell: $env:OPENAI_API_KEY = "..."
export GEMINI_API_KEY=...
export NEMOTRON_API_KEY=...
export VEO_API_KEY=...
```

All model access goes through 엘리스's OpenAI-compatible proxy gateway, not the vendors' own endpoints directly — except Veo 3.1, which is accessed directly against the plain Gemini API and billed out of pocket, so `VEO_API_KEY` is a separate, real Google API key rather than an Elice-issued one. Each real agent resolves its own `base_url` the same way it resolves its API key (explicit constructor arg → env var → SDK default), via these optional per-stage env vars:

```bash
export OPENAI_PLANNING_BASE_URL=...
export OPENAI_STORYBOARD_BASE_URL=...
export OPENAI_PROMPT_BASE_URL=...
export OPENAI_IMAGE_BASE_URL=...
export GEMINI_REVIEW_BASE_URL=...
export NEMOTRON_DIRECTOR_BASE_URL=...
```

`.env.example` lists the key names as a reference. The stub agents do not use these keys yet.
```

Also in `README.md`, update the `## Real agent injection` section's mention of `VideoRenderAgent` — change:

```markdown
`run_pipeline` accepts `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`, `review_agent`, and `director_agent` — pass an instance of the matching real class to use it for that stage instead of the stub. Any not given fall back to their stub, so the pipeline stays fully offline by default. `VideoRenderAgent` has no real implementation yet and cannot be overridden this way.
```

to:

```markdown
`run_pipeline` accepts `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`, `review_agent`, and `director_agent` — pass an instance of the matching real class to use it for that stage instead of the stub. Any not given fall back to their stub, so the pipeline stays fully offline by default. The render stage works differently: `run_pipeline`'s `render_backend` argument (or `model_config.render_backend`) already always constructs a real `VeoBackend` — pass `render_backend=VeoBackend(tier=..., api_key="...")` directly to customize it, the same way you'd construct any of the other real classes.
```

Replace `.env.example` in full:

```bash
# Reference only — this file is NOT auto-loaded (no python-dotenv dependency).
# Export these into your shell environment; config.load_api_keys() reads os.environ.
OPENAI_API_KEY=
GEMINI_API_KEY=
NEMOTRON_API_KEY=

# Veo 3.1 is accessed directly against the plain Gemini API, not through
# Elice's proxy, and is billed out of pocket. Keep this separate from
# GEMINI_API_KEY (which is Elice-issued).
VEO_API_KEY=

# Optional — Elice proxy base URLs, one per stage. Unset means the underlying
# SDK's own default endpoint is used.
OPENAI_PLANNING_BASE_URL=
OPENAI_STORYBOARD_BASE_URL=
OPENAI_PROMPT_BASE_URL=
OPENAI_IMAGE_BASE_URL=
GEMINI_REVIEW_BASE_URL=
NEMOTRON_DIRECTOR_BASE_URL=
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/render_backends/veo_backend.py tests/render_backends/test_veo_backend.py README.md .env.example
git commit -m "feat: implement real VeoBackend against Veo 3.1's Gemini API"
```

---

### Task 3: `StubRenderBackend` — restore offline-by-default (plan amendment)

**Files:**
- Create: `src/video_draft_pipeline/render_backends/stub_backend.py`
- Modify: `src/video_draft_pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/agents/test_video_render_agent.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `schema.Candidate`/`schema.RenderResult` (already exist, unchanged), satisfies the existing `RenderBackend` Protocol (`name: str`, `render(...)`, `estimate_cost(...)`) unchanged.
- Produces: `StubRenderBackend(tier: str = "veo-3.1-fast")` — byte-for-byte the same behavior `VeoBackend` had before Task 2 (no API key, no network call, flat tier pricing with no duration rounding, `stub://veo/<candidate_id>.mp4` clip URLs). `orchestrator.py` consumes it as the new default; nothing outside this task's files needs to change.

- [ ] **Step 1: Write the failing tests**

Exhaustively traced every `VeoBackend` reference in the test suite (see chat context) — exactly two files need editing beyond what Task 2 already touched, because every other failure goes through `run_pipeline`'s *default* construction path and resolves automatically once that default changes.

In `tests/test_orchestrator.py`, change the import:

```python
from video_draft_pipeline.render_backends.veo_backend import VeoBackend
```

to:

```python
from video_draft_pipeline.render_backends.stub_backend import StubRenderBackend
```

and inside `test_run_pipeline_explicit_backend_overrides_model_config`, change:

```python
    project = run_pipeline(
        project_input,
        render_backend=VeoBackend(tier="veo-3.1-lite"),
        model_config=ModelConfig(render_backend="veo-3.1-standard"),
    )
```

to:

```python
    project = run_pipeline(
        project_input,
        render_backend=StubRenderBackend(tier="veo-3.1-lite"),
        model_config=ModelConfig(render_backend="veo-3.1-standard"),
    )
```

In `tests/agents/test_video_render_agent.py`, change the import:

```python
from video_draft_pipeline.render_backends.veo_backend import VeoBackend
```

to:

```python
from video_draft_pipeline.render_backends.stub_backend import StubRenderBackend
```

and replace all four occurrences of `VeoBackend(tier="veo-3.1-fast")` with `StubRenderBackend(tier="veo-3.1-fast")` (in `test_video_render_agent_renders_under_budget`, `test_video_render_agent_raises_when_over_budget`, `test_video_render_agent_raises_without_accepted_candidate`, `test_video_render_agent_raises_when_accepted_candidate_not_in_list`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py tests/agents/test_video_render_agent.py tests/test_cli.py tests/agents/test_factory.py -v`
Expected: FAIL — `stub_backend` module doesn't exist yet (import error), and every test relying on `run_pipeline`'s default construction still hits `VeoBackend`'s `MissingAPIKeyError`.

- [ ] **Step 3: Write the implementation**

Create `src/video_draft_pipeline/render_backends/stub_backend.py`:

```python
from ..schema import Candidate, RenderResult

PRICE_PER_SEC_USD: dict[str, float] = {
    "veo-3.1-lite": 0.05,
    "veo-3.1-fast": 0.10,
    "veo-3.1-standard": 0.40,
}


class StubRenderBackend:
    def __init__(self, tier: str = "veo-3.1-fast"):
        if tier not in PRICE_PER_SEC_USD:
            raise ValueError(f"Unknown Veo tier: {tier}")
        self.tier = tier
        self.name = tier

    def estimate_cost(self, duration_sec: float) -> float:
        return round(PRICE_PER_SEC_USD[self.tier] * duration_sec, 2)

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        cost = self.estimate_cost(duration_sec)
        return RenderResult(
            backend=self.tier,
            status="done",
            clip_url=f"stub://veo/{candidate.candidate_id}.mp4",
            cost_usd=cost,
        )
```

In `src/video_draft_pipeline/orchestrator.py`, change the import:

```python
from .render_backends.veo_backend import VeoBackend
```

to:

```python
from .render_backends.stub_backend import StubRenderBackend
```

and change the backend construction line:

```python
    backend = render_backend or VeoBackend(tier=models.render_backend)
```

to:

```python
    backend = render_backend or StubRenderBackend(tier=models.render_backend)
```

In `README.md`, change the `## Real agent injection` section's render-stage sentence — replace:

```markdown
`run_pipeline` accepts `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`, `review_agent`, and `director_agent` — pass an instance of the matching real class to use it for that stage instead of the stub. Any not given fall back to their stub, so the pipeline stays fully offline by default. The render stage works differently: `run_pipeline`'s `render_backend` argument (or `model_config.render_backend`) already always constructs a real `VeoBackend` — pass `render_backend=VeoBackend(tier=..., api_key="...")` directly to customize it, the same way you'd construct any of the other real classes.
```

with:

```markdown
`run_pipeline` accepts `planning_agent`, `storyboard_agent`, `prompt_agent`, `image_agent`, `review_agent`, `director_agent`, and `render_backend` — pass an instance of the matching real class to use it for that stage instead of the stub. Any not given fall back to their stub, so the pipeline stays fully offline by default. For `render_backend` the stub is `StubRenderBackend` and the real class is `VeoBackend`; inject it the same way as the others: `render_backend=VeoBackend(tier=..., api_key="...")`.
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: All tests pass — every test that was failing due to `run_pipeline`'s default construction (all of `test_cli.py`, `test_factory.py`, the remaining `test_orchestrator.py` failures) resolves automatically since the default now goes through `StubRenderBackend`, which needs no API key.

- [ ] **Step 5: Commit**

```bash
git add src/video_draft_pipeline/render_backends/stub_backend.py src/video_draft_pipeline/orchestrator.py tests/test_orchestrator.py tests/agents/test_video_render_agent.py README.md
git commit -m "fix: restore offline-by-default render stage via StubRenderBackend, make VeoBackend injection-only"
```

---

## Self-Review Notes

- **Spec coverage:** Config layer (Task 1) and the full `VeoBackend` real implementation — construction, tier→model/price mapping, duration rounding, `render()`, polling, error handling, `estimate_cost()`, plus README/`.env.example` docs (Task 2) — cover every section of the approved spec. The spec's explicit "no orchestrator/factory changes needed" claim is honored: neither task touches `orchestrator.py` or `factory.py`.
- **Placeholder scan:** no "TBD"/"handle appropriately"/"similar to Task N" phrasing; every step shows complete code.
- **Type consistency:** `VeoBackend`'s constructor signature, `model_id`/`price_per_sec_usd` attribute names, and `VeoBackendError`/`_round_to_allowed_duration` names are identical between Task 2's test file (Step 1) and implementation (Step 3). `estimate_cost()`'s rounding logic is textually identical in both `render()` and `estimate_cost()` (via `_round_to_allowed_duration`), which is what the drift test (`test_estimate_cost_matches_render_reported_cost`) verifies.
- **Existing test fallout, deliberately handled:** the pre-existing `test_veo_backend_fast_tier_cost_math`/`test_veo_backend_lite_tier_cost_math` (which construct `VeoBackend()` with zero arguments and assert on `stub://veo/...`) are superseded by Task 2's `test_render_calls_sdk_with_expected_model_image_and_config` and `test_render_lite_tier_cost_math`, which assert the same cost values (`0.60`/`0.30` at `duration_sec=6.0`, an already-allowed duration so rounding doesn't change the expected numbers) against the new real-call-shaped construction. `test_veo_backend_rejects_unknown_tier` is carried over unchanged since tier validation happens before key resolution and needs no client.
- **Plan amendment (Task 3), discovered mid-implementation:** Task 2's original Global Constraints wrongly claimed no orchestrator changes were needed. In reality, making `VeoBackend` fail-fast while it remained the orchestrator's unconditional default broke the project's own "offline unless real agents are explicitly injected" guarantee — not just for tests, but for the actual documented CLI invocation. Task 2's implementer caught this, reported `DONE_WITH_CONCERNS` rather than silently working around it, and the human partner confirmed the fix direction (reinstate a stub/real split for render, matching all 6 other stages) before Task 3 was written. Every affected call site was traced exhaustively (grepped for `VeoBackend` across the whole test suite) before writing Task 3, so its diff is exact rather than exploratory.
- **Undocumented plan deviation, caught by the final whole-branch review:** the spec and this plan's Task 2 both specify `types.Image.from_bytes(data=image_bytes, mime_type="image/png")` for the `image` kwarg. The installed `google-genai>=2.15` SDK has no `from_bytes` classmethod on `types.Image` — that line would have raised `AttributeError` on the first real call. Task 2's implementer correctly substituted the equivalent direct construction, `types.Image(image_bytes=image_bytes, mime_type="image/png")`, verified against the installed SDK's actual `types.Image.model_fields` (`gcs_uri`/`image_bytes`/`mime_type`). This is a latent bug in the approved spec's own code sample, not an implementer error — recorded here since the spec itself is not being retroactively edited.
- **Follow-up work identified by the final review, deferred (not blocking this plan):**
  1. **Duration-rounding can silently exceed `ProjectInput.max_duration_sec`.** `StoryboardAgent` divides the requested total duration across N scenes into arbitrary floats; `VeoBackend` then rounds each scene independently to the nearest of `{4,6,8}`, and rounding can go up. Worked example: `--duration 30` across 4 beats → 7.5s/scene → each rounds to 8s → 32s of actual delivered video against a 30s cap the pipeline already enforced upstream. Cost stays honest (`estimate_cost` rounds identically), but nothing records that the delivered clip duration differs from `scene.duration_sec` (`RenderResult` has no duration field). Dormant today since `StubRenderBackend` — the actual default — doesn't round at all; must be resolved before real `VEO_API_KEY` access is provisioned. Likely fix belongs upstream (storyboard-stage duration allocation from `{4,6,8}` when a rounding-constrained backend is in play), not in `VeoBackend` itself — future spec.
  2. **`_poll_until_done` has no timeout or attempt cap.** A Veo operation that never reports `done` would hang the pipeline indefinitely. Untestable without real Veo access; noted for when real keys land.
