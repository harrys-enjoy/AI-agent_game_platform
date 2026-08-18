from ..schema import Candidate, ConsistencyReview, Prompts


class ReviewAgent:
    def __init__(self, reviewer_name: str = "gemini-3-pro-image"):
        self.reviewer_name = reviewer_name

    def run(self, candidate: Candidate, prior_candidates: list[Candidate], prompts: Prompts) -> ConsistencyReview:
        return ConsistencyReview(reviewed_by=self.reviewer_name, passed=True, issues=[])

    def estimate_cost(self) -> float:
        return 0.0
