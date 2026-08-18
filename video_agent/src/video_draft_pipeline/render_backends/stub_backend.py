from ..schema import Candidate, RenderResult

PRICE_PER_SEC_USD: dict[str, float] = {
    "veo-3.1-lite": 0.05,
    "veo-3.1-fast": 0.10,
    "veo-3.1-standard": 0.40,
}


class StubRenderBackend:
    def __init__(self, tier: str = "veo-3.1-fast"):
        if tier not in PRICE_PER_SEC_USD:
            raise ValueError(f"Unknown Veo tier: {tier}")
        self.tier = tier
        self.name = tier

    def estimate_cost(self, duration_sec: float) -> float:
        return round(PRICE_PER_SEC_USD[self.tier] * duration_sec, 2)

    def render(self, candidate: Candidate, motion_prompt: str, duration_sec: float) -> RenderResult:
        cost = self.estimate_cost(duration_sec)
        return RenderResult(
            backend=self.tier,
            status="done",
            clip_url=f"stub://veo/{candidate.candidate_id}.mp4",
            cost_usd=cost,
        )
