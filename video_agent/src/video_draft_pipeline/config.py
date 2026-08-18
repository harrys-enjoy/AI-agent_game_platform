import os
from dataclasses import dataclass
from pathlib import Path

# Fallback locations for keys that were never typed into a terminal or chat --
# create these by hand, outside the repo, containing just the key on one line.
GEMINI_API_KEY_FILE = Path.home() / ".gemini_api_key"
VEO_API_KEY_FILE = Path.home() / ".veo_api_key"
LTX_API_KEY_FILE = Path.home() / ".ltx_api_key"


def _resolve_key(env_var: str, file_fallback: Path) -> str | None:
    value = os.environ.get(env_var)
    if value:
        return value
    if file_fallback.exists():
        return file_fallback.read_text().strip()
    return None


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


@dataclass
class ApiKeys:
    gemini_api_key: str | None = None
    veo_api_key: str | None = None
    ltx_api_key: str | None = None


def load_api_keys() -> ApiKeys:
    return ApiKeys(
        gemini_api_key=_resolve_key("GEMINI_API_KEY", GEMINI_API_KEY_FILE),
        veo_api_key=_resolve_key("VEO_API_KEY", VEO_API_KEY_FILE),
        ltx_api_key=_resolve_key("LTX_API_KEY", LTX_API_KEY_FILE),
    )
