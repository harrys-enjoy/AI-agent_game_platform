import json
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from pydantic import BaseModel

from .. import config
from .errors import MissingAPIKeyError

_IMAGE_MIME_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}
_IMAGE_EXTENSION_MIME_TYPES = {ext: mime for mime, ext in _IMAGE_MIME_TYPE_EXTENSIONS.items()}


def extension_for_image_mime_type(mime_type: str | None) -> str:
    return _IMAGE_MIME_TYPE_EXTENSIONS.get(mime_type, ".png")


def mime_type_for_image_path(path: str | Path) -> str:
    return _IMAGE_EXTENSION_MIME_TYPES.get(Path(path).suffix.lower(), "image/png")


class BaseGeminiAgent:
    error_cls: type[Exception]

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        client: genai.Client | None = None,
        base_url: str | None = None,
        log_path: str | Path | None = None,
    ):
        resolved_key = api_key or config.load_api_keys().gemini_api_key
        if not resolved_key:
            raise MissingAPIKeyError(
                "No Gemini API key found: pass api_key explicitly, set GEMINI_API_KEY, "
                "or put the key in ~/.gemini_api_key."
            )
        http_options = {"base_url": base_url} if base_url else None
        self.model_name = model_name
        self.api_key = resolved_key
        self._client = client or genai.Client(api_key=resolved_key, http_options=http_options)
        self._log_path = Path(log_path) if log_path else None

    def _log_interaction(self, input_content: list[dict], output: object) -> None:
        if self._log_path is None:
            return
        sanitized_input = [
            {**item, "data": f"<{len(item['data'])} base64 chars omitted>"}
            if item.get("type") == "image"
            else item
            for item in input_content
        ]
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": type(self).__name__,
            "model": self.model_name,
            "input": sanitized_input,
            "output": output,
        }
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _structured_interaction(self, input_content: list[dict], response_schema: type[BaseModel]) -> BaseModel:
        try:
            interaction = self._client.interactions.create(
                model=self.model_name,
                input=input_content,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema.model_json_schema(),
                },
            )
        except Exception as exc:
            raise self.error_cls(f"Gemini call failed: {exc}") from exc
        try:
            parsed = response_schema.model_validate_json(interaction.output_text)
        except Exception as exc:
            raise self.error_cls(f"Gemini call returned unparseable output: {exc}") from exc
        self._log_interaction(input_content, parsed.model_dump())
        return parsed
