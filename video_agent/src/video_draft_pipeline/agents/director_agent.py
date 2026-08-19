from ..schema import Scene, ConsistencyReview, DirectorDecision


class DirectorAgent:
    def __init__(self, director_name: str = "nemotron-3-ultra"):
        self.director_name = director_name

    def run(self, scene: Scene, review: ConsistencyReview) -> DirectorDecision:
        if review.passed:
            return DirectorDecision(decision="accept", decided_by=self.director_name)

        if scene.retry_count >= scene.max_retries:
            return DirectorDecision(
                decision="reject",
                feedback="Max retries exhausted without a passing review.",
                decided_by=self.director_name,
            )

        return DirectorDecision(
            decision="regenerate",
            feedback="; ".join(review.issues) or "Consistency review failed.",
            decided_by=self.director_name,
        )

    def estimate_cost(self) -> float:
        return 0.0
