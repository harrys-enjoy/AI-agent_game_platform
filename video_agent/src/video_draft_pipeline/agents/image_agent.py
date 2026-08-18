import uuid

from ..schema import Prompts, Candidate


class ImageAgent:
    def __init__(self, model_name: str = "gpt-image-2"):
        self.model_name = model_name

    def run(self, prompts: Prompts, reference_image_urls: list[str] | None = None) -> Candidate:
        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        return Candidate(
            candidate_id=candidate_id,
            image_url=f"stub://{self.model_name}/{candidate_id}.png",
            generated_by=self.model_name,
        )

    def estimate_cost(self) -> float:
        return 0.0
