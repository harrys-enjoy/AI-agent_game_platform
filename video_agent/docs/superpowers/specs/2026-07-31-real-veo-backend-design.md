# Real VeoBackend (Veo 3.1) — design spec

## Context

Of the pipeline's 7 stages, `VideoRenderAgent`/`VeoBackend` is the last one still a pure stub: `VeoBackend.render()` returns a hardcoded `stub://veo/<candidate_id>.mp4` clip URL and never calls a real API, even though it already has real-shaped tiered pricing (`PRICE_PER_SEC_USD`: lite `0.05`, fast `0.10`, standard `0.40` per second) and is already the pipeline's unconditional default render backend (`orchestrator.py` does `backend = render_backend or VeoBackend(tier=models.render_backend)` — unlike the other 6 stages, there was never a separate stub-class/real-class split here, just one `VeoBackend` class that happened to fake its output).

Veo 3.1 is confirmed (per this session's prior Elice-proxy-retrofit spec) to be accessed directly, out of pocket — not through 엘리스's proxy. The user provided real Gemini API documentation for `google-genai`'s `client.models.generate_videos(...)` interface, including: dialogue/SFX/ambient-audio prompting, aspect ratio control, image-to-video generation, reference images, video extension, the async operation/polling model, the full parameter/spec table by model tier, and confirmed real per-second pricing by resolution:

| Tier | Model ID (Gemini API, `-preview` suffix) | 720p | 1080p | 4k |
|---|---|---|---|---|
| lite | `veo-3.1-lite-generate-preview` | $0.05/s | $0.08/s | not supported |
| fast | `veo-3.1-fast-generate-preview` | $0.10/s | $0.12/s | $0.30/s |
| standard | `veo-3.1-generate-preview` | $0.40/s | $0.40/s | $0.60/s |

The existing stub's flat per-tier prices already exactly match the real 720p prices above.

**Platform ambiguity, resolved:** the user also found separate model-card documentation for `-001`-suffixed model IDs (e.g. `veo-3.1-generate-001`) describing GCP region availability (`us-central1`), enterprise security controls (CMEK, VPC-SC), and "Provisioned Throughput" billing — this is Vertex AI's enterprise model catalog, a different platform with project/service-account auth, not the plain API-key-based Gemini API every other real agent in this codebase uses. That documentation's capability flags (e.g. "Sound generation: Not Supported" on some models) contradict the plain Gemini API docs' "Audio: Always on," which is consistent with it describing a different platform rather than a real capability regression. This design targets the **plain Gemini API** (`veo-3.1-*-generate-preview` model IDs, `genai.Client(api_key=...)`), matching every original code sample provided and this codebase's existing simple-API-key auth convention. The Vertex AI catalog is out of scope.

## Goals

- `VeoBackend.render()` makes a real Veo 3.1 call: takes the scene's already-generated candidate image and motion prompt, generates an image-to-video clip with native audio, downloads it locally, and returns a real `RenderResult`.
- `VeoBackend.estimate_cost()` reflects real per-tier, 720p pricing, and never drifts from what `render()` actually reports as `cost_usd` for the same duration.
- Tier (`"veo-3.1-lite"` / `"veo-3.1-fast"` / `"veo-3.1-standard"`) maps to the correct real model ID and price — the existing `RenderBackendName` literal and `ModelConfig.render_backend` default (`"veo-3.1-fast"`) are unchanged.
- `VEO_API_KEY` follows the same explicit-param → env-var → fail-fast convention as every other real agent, kept separate from `GEMINI_API_KEY` (which is Elice-routed) since this is a distinct, directly-billed credential.

## Non-goals

- `SelfHostedBackend` and any per-scene backend-selection logic (some scenes → Veo, others → a free self-hosted diffusion model + audio model) — explicitly deferred to a future spec once this real `VeoBackend` exists to design selection against.
- The LTX 2.3 model mentioned as a possible future cheap/lightweight option — noted for later, not evaluated here.
- 1080p/4k resolution support — v1 fixes resolution at 720p for all tiers (matches the pricing table's "(default)" framing, avoids the duration-lock quirk where 1080p/4k force `duration_seconds="8"`). Configurable resolution is a future enhancement if ever needed.
- Reference images (up to 3), video extension (`video=`/`lastFrame=` params), and multi-video-per-request output — none of these fit `VideoRenderAgent`'s current single-image-in/single-clip-out signature; deferred.
- Any `run_pipeline`/`build_real_agents()`/orchestrator changes — none are needed. `VeoBackend` was already the unconditional default `render_backend` before this spec; making its internals real doesn't change how or when it's constructed.
- Live-API or integration tests against Veo — no real `VEO_API_KEY` exists yet, consistent with every other spec in this project. The `google-genai` vs. Vertex AI platform assumption above is unverified until real keys exist to test against.

## Design

### Config layer (`config.py`)

`ApiKeys` gains one new field, following the exact pattern of `openai_api_key`/`gemini_api_key`/`nemotron_api_key`:

```python
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

`VeoBackend` resolves its key via `config.load_api_keys().veo_api_key`, kept intentionally separate from `gemini_api_key` (Elice-routed, used by `GeminiReviewAgent`) since `VEO_API_KEY` is a distinct, directly-billed-to-the-user credential — mixing them up would risk a real charge landing on the wrong key or a live Veo call silently going through Elice's proxy (which doesn't support it).

### `VeoBackend` construction

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
        self.model_id = MODEL_ID_BY_TIER[tier]
        self.price_per_sec_usd = PRICE_PER_SEC_USD[tier]
        self.poll_interval_sec = poll_interval_sec
        self._client = client or genai.Client(api_key=resolved_key)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
```

`min(..., key=lambda allowed: (abs(allowed - duration_sec), -allowed))` picks the closest allowed duration, breaking exact ties (e.g. `duration_sec=5.0`, equidistant from 4 and 6) toward the larger value via the `-allowed` tiebreaker. `MissingAPIKeyError` is reused from `agents/openai_agent_base.py` — no duplicate exception, matching every other real component's convention.

### `render()`

```python
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

`candidate.image_url` is always a local file path at this point in the pipeline (written by `OpenAIImageAgent`), so `Path(...).read_bytes()` needs no additional error handling beyond what already exists upstream. `render()` calls `self.estimate_cost(duration_sec)` with the original, un-rounded float — rounding is idempotent, so this always matches what the orchestrator's pre-charge budget guard already computed via the same `estimate_cost()` call.

## Testing

- `tests/render_backends/test_veo_backend.py`:
  - Constructor: missing key → `MissingAPIKeyError`; explicit key precedence over env; unknown tier → `ValueError` (existing test, unchanged); each tier resolves the correct `model_id` and `price_per_sec_usd`; `output_dir` created if missing.
  - `_round_to_allowed_duration`: table-driven tests covering values below 4, between each pair, above 8, and the exact tie-break case.
  - `render()`: `MagicMock()` client where `models.generate_videos` returns a fake operation (`done=False`, becoming `done=True` only after one `operations.get()` call, proving the poll loop actually loops); `poll_interval_sec=0` in tests so nothing really sleeps; a fake `generated_videos[0].video` whose `.save(path)` writes real bytes to `path` (same technique `OpenAIImageAgent`'s tests already use for `tmp_path`) — assert the correct `model` kwarg per tier, `image` built from the candidate's actual file bytes, `duration_seconds` rounded correctly, `aspect_ratio="16:9"`, `generate_audio=True`, and that the returned `RenderResult.clip_url` points at a real file containing the mock's bytes.
  - Error paths, each asserting `VeoBackendError`: SDK exception from `generate_videos`; empty/missing `generated_videos`; exception from `files.download`/`video.save`.
  - `estimate_cost()`: per-tier pricing correctness, and cross-checked against `render()`'s reported `cost_usd` for the same duration to prove no drift.
- `tests/test_config.py`: `veo_api_key`/`VEO_API_KEY` added to the existing `load_api_keys` env-read tests, following the same pattern as the other key fields.
- No live-API tests — no real `VEO_API_KEY` exists in this environment yet.

## Open questions / follow-ups (not blocking this spec)

- 1080p/4k resolution support, and whether resolution should become a per-instance option — deferred until there's an actual need.
- `SelfHostedBackend`'s real implementation (free self-hosted diffusion model + audio model) and the per-scene backend-selection logic that would pick between it and `VeoBackend` — explicitly out of scope, future spec.
- LTX 2.3 as a possible additional/alternative cheap render option — noted, not designed.
- Whether the plain Gemini API (this spec's target) vs. Vertex AI's enterprise catalog is really the right platform can only be confirmed once real Veo access is provisioned — if it turns out Vertex AI is actually what's provisioned, the auth/client construction in `VeoBackend.__init__` would need rework (GCP project/service-account auth instead of a plain API key), though the `render()`/polling/download logic shape would likely stay similar.
- Reference images, video extension (`video=`/`lastFrame=`), and multi-clip-per-request — deferred, no current use case in this pipeline's single-image-in/single-clip-out flow.
