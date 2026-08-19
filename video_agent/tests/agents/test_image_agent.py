from video_draft_pipeline.schema import Prompts
from video_draft_pipeline.agents.image_agent import ImageAgent


def test_image_agent_returns_candidate_with_stub_url():
    prompts = Prompts(image_prompt="a castle at night", video_motion_prompt="pan left")

    candidate = ImageAgent(model_name="gpt-image-2").run(prompts)

    assert candidate.generated_by == "gpt-image-2"
    assert candidate.image_url.startswith("stub://gpt-image-2/")
    assert candidate.candidate_id


def test_image_agent_generates_unique_candidate_ids():
    prompts = Prompts(image_prompt="a castle", video_motion_prompt="pan")
    agent = ImageAgent()

    c1 = agent.run(prompts)
    c2 = agent.run(prompts)

    assert c1.candidate_id != c2.candidate_id


def test_image_agent_estimate_cost_is_zero():
    assert ImageAgent().estimate_cost() == 0.0
