import time
from pathlib import Path

from google import genai
from google.genai import types

from .. import config
from ..agents.errors import MissingAPIKeyError
from ..agents.gemini_agent_base import mime_type_for_image_path
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
ALLOWED_RESOLUTIONS = ("720p", "1080p", "4k")


def _round_to_allowed_duration(duration_sec: float) -> int:
    return min(ALLOWED_DURATIONS, key=lambda allowed: (abs(allowed - duration_sec), -allowed))


class VeoBackendError(Exception):
    pass


class VeoBackend:
    def __init__(
        self,
        tier: str = "veo-3.1-fast",
        resolution: str = "720p",
        api_key: str | None = None,
        client: genai.Client | None = None,
        output_dir: str | Path = "media",
        poll_interval_sec: float = 10.0,
    ):
        if tier not in PRICE_PER_SEC_USD:
            raise ValueError(f"Unknown Veo tier: {tier}")
        if resolution not in ALLOWED_RESOLUTIONS:
            raise ValueError(f"Unknown Veo resolution: {resolution}")
        if resolution == "4k" and tier == "veo-3.1-lite":
            raise ValueError("4k is not available for veo-3.1-lite")
        resolved_key = api_key or config.load_api_keys().veo_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No Veo API key found: pass api_key explicitly, set VEO_API_KEY, "
                "or put the key in ~/.veo_api_key."
            )
        self.tier = tier
        self.resolution = resolution
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

        try:
            image_bytes = Path(candidate.image_url).read_bytes()
            operation = self._client.models.generate_videos(
                model=self.model_id,
                prompt=motion_prompt,
                image=types.Image(
                    image_bytes=image_bytes,
                    mime_type=mime_type_for_image_path(candidate.image_url),
                ),
                # generate_audio is Enterprise/Vertex-only — the google-genai SDK raises
                # unconditionally if it's set at all under plain API-key (Developer API)
                # auth, which is how this client is constructed. Confirmed via a real
                # live call (2026-08-01); do not re-add without switching client modes.
                config=types.GenerateVideosConfig(
                    aspect_ratio="16:9",
                    duration_seconds=requested_duration,
                    resolution=self.resolution,
                ),
            )
            operation = self._poll_until_done(operation)
        except OSError as exc:
            raise VeoBackendError(
                f"Could not read candidate image at {candidate.image_url!r}: {exc}. "
                "VeoBackend requires the image stage to produce a real local file "
                "(e.g. GeminiImageAgent) — the stub ImageAgent's fake paths won't work."
            ) from exc
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
