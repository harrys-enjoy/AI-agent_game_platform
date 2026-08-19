from video_draft_pipeline.schema import Scene, Storyboard, ConsistencyReview
from video_draft_pipeline.agents.director_agent import DirectorAgent


def _scene(retry_count: int = 0, max_retries: int = 3) -> Scene:
    return Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        retry_count=retry_count,
        max_retries=max_retries,
    )


def test_director_accepts_when_review_passed():
    review = ConsistencyReview(reviewed_by="gemini-3-pro-image", passed=True, issues=[])

    decision = DirectorAgent().run(_scene(), review)

    assert decision.decision == "accept"
    assert decision.decided_by == "nemotron-3-ultra"


def test_director_regenerates_when_review_failed_and_retries_remain():
    review = ConsistencyReview(
        reviewed_by="gemini-3-pro-image", passed=False, issues=["색감 불일치"]
    )

    decision = DirectorAgent().run(_scene(retry_count=1, max_retries=3), review)

    assert decision.decision == "regenerate"
    assert "색감 불일치" in decision.feedback


def test_director_rejects_when_retries_exhausted():
    review = ConsistencyReview(
        reviewed_by="gemini-3-pro-image", passed=False, issues=["색감 불일치"]
    )

    decision = DirectorAgent().run(_scene(retry_count=3, max_retries=3), review)

    assert decision.decision == "reject"


def test_estimate_cost_returns_zero():
    assert DirectorAgent().estimate_cost() == 0.0
