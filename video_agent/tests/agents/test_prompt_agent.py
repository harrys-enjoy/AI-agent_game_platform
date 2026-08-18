from video_draft_pipeline.schema import Scene, Storyboard
from video_draft_pipeline.agents.prompt_agent import PromptAgent


def test_prompt_agent_builds_image_and_motion_prompts():
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6,
        storyboard=Storyboard(
            camera="슬로우 팬, 성벽 따라 이동",
            subject="호박 몬스터 무리",
            action="성벽을 타고 올라옴",
            setting="성 외곽, 야간",
        ),
    )

    prompts = PromptAgent().run(scene)

    assert "호박 몬스터 무리" in prompts.image_prompt
    assert "성벽을 타고 올라옴" in prompts.image_prompt
    assert "슬로우 팬, 성벽 따라 이동" in prompts.video_motion_prompt


def test_prompt_agent_accepts_injected_model_name():
    assert PromptAgent().prompt_model == "gpt-5-mini"
    assert PromptAgent("custom-prompter").prompt_model == "custom-prompter"


def test_prompt_agent_estimate_cost_is_zero():
    assert PromptAgent().estimate_cost() == 0.0


def test_prompt_agent_accepts_and_ignores_feedback():
    scene = Scene(
        scene_id="scene_01",
        beat_id="conflict",
        order=1,
        duration_sec=6,
        storyboard=Storyboard(
            camera="슬로우 팬, 성벽 따라 이동",
            subject="호박 몬스터 무리",
            action="성벽을 타고 올라옴",
            setting="성 외곽, 야간",
        ),
    )

    with_feedback = PromptAgent().run(scene, feedback="fix the lighting")
    without_feedback = PromptAgent().run(scene)

    assert with_feedback == without_feedback
