import uuid

from ..schema import Candidate, Prompts


class ImageEditAgent:
    def __init__(self, model_name: str = "gemini-2.5-flash-image"):
        self.model_name = model_name

    def run(self, candidate: Candidate, prompts: Prompts, feedback: str) -> Candidate:
        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        return Candidate(
            candidate_id=candidate_id,
            image_url=f"stub://{self.model_name}/{candidate_id}.png",
            generated_by=self.model_name,
        )

    def estimate_cost(self) -> float:
        return 0.0
