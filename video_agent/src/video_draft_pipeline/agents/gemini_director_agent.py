from pydantic import BaseModel

from ..schema import ConsistencyReview, Decision, DirectorDecision, Scene
from .gemini_agent_base import BaseGeminiAgent


def _build_input(scene: Scene, review: ConsistencyReview) -> str:
    issues = "; ".join(review.issues) or "none"
    return (
        "You are the creative director for a game marketing video draft. You "
        "decide whether a generated scene image should be accepted, "
        "regenerated, or rejected outright, based on a consistency review.\n\n"
        f"Scene: {scene.scene_id} ({scene.beat_id})\n"
        f"Review passed: {review.passed}\n"
        f"Review issues: {issues}\n"
        f"Retry count so far: {scene.retry_count} / max {scene.max_retries}\n"
        "Decide: accept (image is usable as-is), regenerate (image should be "
        "attempted again), or reject (give up on this scene). Give a short "
        "reason in feedback."
    )


class DirectorAgentError(Exception):
    pass


class DirectorVerdict(BaseModel):
    decision: Decision
    feedback: str | None = None


class GeminiDirectorAgent(BaseGeminiAgent):
    error_cls = DirectorAgentError
    ESTIMATED_COST_USD = 0.03

    def __init__(
        self,
        model_name: str = "gemini-3.6-flash",
        api_key: str | None = None,
        client=None,
        base_url: str | None = None,
        log_path=None,
    ):
        super().__init__(model_name, api_key, client, base_url, log_path)

    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision:
        input_content = [{"type": "text", "text": _build_input(scene, review)}]
        verdict = self._structured_interaction(input_content, DirectorVerdict)
        decision = verdict.decision
        if decision == "regenerate" and scene.retry_count >= scene.max_retries:
            # Can't grant another attempt once retries are exhausted, but an
            # accept/reject verdict is already terminal and needs no override.
            decision = "reject"
        return DirectorDecision(decision=decision, feedback=verdict.feedback, decided_by=self.model_name)

    def estimate_cost(self) -> float:
        return self.ESTIMATED_COST_USD
