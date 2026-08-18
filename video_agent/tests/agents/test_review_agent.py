from video_draft_pipeline.agents.review_agent import ReviewAgent
from video_draft_pipeline.schema import Candidate, Prompts


def test_review_agent_stub_always_passes_with_no_issues():
    candidate = Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")

    review = ReviewAgent(reviewer_name="gemini-3-pro-image").run(
        candidate, prior_candidates=[], prompts=prompts
    )

    assert review.reviewed_by == "gemini-3-pro-image"
    assert review.passed is True
    assert review.issues == []


def test_review_agent_estimate_cost_is_zero():
    assert ReviewAgent().estimate_cost() == 0.0
