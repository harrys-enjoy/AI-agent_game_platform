import base64
import uuid
from pathlib import Path

from ..schema import Candidate, Prompts
from .gemini_agent_base import BaseGeminiAgent, extension_for_image_mime_type, mime_type_for_image_path


class ImageEditAgentError(Exception):
    pass


class GeminiImageEditAgent(BaseGeminiAgent):
    error_cls = ImageEditAgentError
    ESTIMATED_COST_USD = 0.134

    def __init__(
        self,
        model_name: str = "gemini-3-pro-image",
        output_dir: str | Path = "media",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
        log_path=None,
    ):
        super().__init__(model_name, api_key, client, base_url, log_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate:
        try:
            image_bytes = Path(candidate.image_url).read_bytes()
        except OSError as exc:
            raise self.error_cls(f"Could not read candidate image at {candidate.image_url!r}: {exc}") from exc
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        input_content = [
            {
                "type": "text",
                "text": (
                    "Edit this AI-generated image for a game marketing video scene to address "
                    f"the following director feedback: {feedback}\n"
                    f"Keep the edit consistent with the original prompt: {prompts.image_prompt}"
                ),
            },
            {"type": "image", "data": image_b64, "mime_type": mime_type_for_image_path(candidate.image_url)},
        ]

        try:
            interaction = self._client.interactions.create(model=self.model_name, input=input_content)
        except Exception as exc:
            raise self.error_cls(f"Gemini image-edit call failed: {exc}") from exc

        if interaction.output_image is None:
            raise self.error_cls("Gemini image-edit call returned no output image")

        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        edited_bytes = base64.b64decode(interaction.output_image.data)
        extension = extension_for_image_mime_type(getattr(interaction.output_image, "mime_type", None))
        file_path = self.output_dir / f"{candidate_id}{extension}"
        file_path.write_bytes(edited_bytes)

        self._log_interaction(input_content, {"candidate_id": candidate_id, "image_path": str(file_path)})
        return Candidate(
            candidate_id=candidate_id,
            image_url=str(file_path),
            generated_by=self.model_name,
        )

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
