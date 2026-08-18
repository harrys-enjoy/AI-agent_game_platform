from video_draft_pipeline.schema import Candidate, Prompts
from video_draft_pipeline.agents.image_edit_agent import ImageEditAgent


def _prior_candidate() -> Candidate:
    return Candidate(
        candidate_id="cand_prior", image_url="stub://gpt-image-2/cand_prior.png", generated_by="gpt-image-2"
    )


def test_image_edit_agent_returns_candidate_with_stub_url():
    prompts = Prompts(image_prompt="a castle at night", video_motion_prompt="pan left")

    candidate = ImageEditAgent(model_name="gemini-2.5-flash-image").run(
        _prior_candidate(), prompts, feedback="fix the lighting"
    )

    assert candidate.generated_by == "gemini-2.5-flash-image"
    assert candidate.image_url.startswith("stub://gemini-2.5-flash-image/")
    assert candidate.candidate_id


def test_image_edit_agent_generates_unique_candidate_ids():
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")
    agent = ImageEditAgent()

    c1 = agent.run(_prior_candidate(), prompts, feedback="fix it")
    c2 = agent.run(_prior_candidate(), prompts, feedback="fix it again")

    assert c1.candidate_id != c2.candidate_id


def test_image_edit_agent_estimate_cost_is_zero():
    assert ImageEditAgent().estimate_cost() == 0.0
