import base64
from pathlib import Path

import requests

from .. import config
from ..agents.errors import MissingAPIKeyError
from ..agents.gemini_agent_base import mime_type_for_image_path
from ..schema import Candidate, RenderResult

API_URL = "https://api.ltx.io/v1/image-to-video"

PRICE_PER_SEC_USD: dict[str, dict[str, float]] = {
    "ltx-2-3-fast": {
        "1920x1080": 0.06,
        "1080x1920": 0.06,
        "2560x1440": 0.12,
        "1440x2560": 0.12,
        "3840x2160": 0.24,
        "2160x3840": 0.24,
    },
    "ltx-2-3-pro": {
        "1920x1080": 0.08,
        "1080x1920": 0.08,
        "2560x1440": 0.16,
        "1440x2560": 0.16,
        "3840x2160": 0.32,
        "2160x3840": 0.32,
    },
}


class LTXBackendError(Exception):
    pass


class LTXBackend:
    def __init__(
        self,
        model: str = "ltx-2-3-fast",
        resolution: str = "1920x1080",
        api_key: str | None = None,
        output_dir: str | Path = "media",
    ):
        if model not in PRICE_PER_SEC_USD or resolution not in PRICE_PER_SEC_USD[model]:
            raise ValueError(f"Unknown LTX model/resolution combination: {model}/{resolution}")
        resolved_key = api_key or config.load_api_keys().ltx_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No LTX API key found: pass api_key explicitly, set LTX_API_KEY, "
                "or put the key in ~/.ltx_api_key."
            )
        self.model = model
        self.resolution = resolution
        self.name = model
        self.api_key = resolved_key
        self.price_per_sec_usd = PRICE_PER_SEC_USD[model][resolution]
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        try:
            image_bytes = Path(candidate.image_url).read_bytes()
        except OSError as exc:
            raise LTXBackendError(
                f"Could not read candidate image at {candidate.image_url!r}: {exc}. "
                "LTXBackend requires the image stage to produce a real local file "
                "(e.g. GeminiImageAgent) — the stub ImageAgent's fake paths won't work."
            ) from exc
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "image_uri": f"data:{mime_type_for_image_path(candidate.image_url)};base64,{image_b64}",
            "prompt": motion_prompt,
            "model": self.model,
            "duration": round(duration_sec),
            "resolution": self.resolution,
            "generate_audio": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        try:
            response = requests.post(API_URL, json=payload, headers=headers)
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise LTXBackendError(f"LTX video generation failed: {exc}") from exc

        clip_path = self.output_dir / f"{candidate.candidate_id}.mp4"
        clip_path.write_bytes(response.content)

        return RenderResult(
            backend=self.model,
            status="done",
            clip_url=str(clip_path),
            cost_usd=self.estimate_cost(duration_sec),
        )

    def estimate_cost(self, duration_sec: float) -> float:
        return round(self.price_per_sec_usd * round(duration_sec), 2)
