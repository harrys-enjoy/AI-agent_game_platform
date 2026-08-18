from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_prompt_agent import (
    GeminiPromptAgent,
    PromptAgentError,
    _build_input,
)
from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.schema import Prompts, Scene, Storyboard


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiPromptAgent()


def test_default_model_name_is_gemini_3_5_flash_lite(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPromptAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.5-flash-lite"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPromptAgent(model_name="custom-prompter", client=MagicMock())

    assert agent.model_name == "custom-prompter"


def _scene(required_elements=None):
    return Scene(
        scene_id="scene_01", beat_id="conflict", order=1, duration_sec=6,
        storyboard=Storyboard(
            camera="슬로우 팬, 성벽 따라 이동", subject="호박 몬스터 무리",
            action="성벽을 타고 올라옴", setting="성 외곽, 야간",
            required_elements=required_elements or [],
        ),
    )


def test_build_input_includes_storyboard_fields():
    text = _build_input(_scene())

    assert "슬로우 팬, 성벽 따라 이동" in text
    assert "호박 몬스터 무리" in text


def test_build_input_includes_feedback_when_present():
    text = _build_input(_scene(), feedback="fix the lighting")

    assert "fix the lighting" in text


def test_build_input_omits_feedback_section_when_none():
    text = _build_input(_scene(), feedback=None)

    assert "director" not in text.lower()


def test_build_input_instructs_against_on_image_text():
    text = _build_input(_scene())

    assert "on-image text" in text


def test_build_input_instructs_english_output_despite_korean_input():
    text = _build_input(_scene())

    assert "EXCLUSIVELY IN ENGLISH" in text


def test_build_input_forbids_camera_movement_verbs_in_image_prompt():
    text = _build_input(_scene())

    assert "camera movement verbs" in text
    assert "pan, zoom, dolly, track" in text


def test_build_input_includes_beat_intensity_for_known_beat_id():
    scene = _scene()
    assert scene.beat_id == "conflict"

    text = _build_input(scene)

    assert "tense, uneasy" in text


def test_build_input_includes_style_guide_fields_when_present():
    scene = Scene(
        scene_id="scene_01", beat_id="climax", order=1, duration_sec=6,
        storyboard=Storyboard(
            camera="pan", subject="a knight", action="draws sword", setting="castle",
            visual_style="3D cinematic render", color_palette="teal and orange",
        ),
    )

    text = _build_input(scene)

    assert "3D cinematic render" in text
    assert "teal and orange" in text


def test_build_input_shows_unspecified_when_style_guide_fields_empty():
    text = _build_input(_scene())

    assert "unspecified" in text


def test_build_input_instructs_pov_shots_to_hide_subject_face_and_body():
    text = _build_input(_scene())

    assert "point-of-view" in text
    assert "do NOT describe the Subject's face, helmet, or body" in text


def test_build_input_instructs_wide_drone_shots_to_minimize_subject_detail():
    text = _build_input(_scene())

    assert "aerial/drone" in text
    assert "brief, distant mention" in text


def test_build_input_forbids_blending_scope_reticle_and_visible_gun_body():
    text = _build_input(_scene())

    assert "pure scope-reticle HUD" in text
    assert "in-world aim-down-sights" in text
    assert "do not describe both at once" in text


def test_build_input_forbids_video_motion_prompt_from_introducing_ungrounded_effects():
    text = _build_input(_scene())

    assert "must not introduce any object, effect" in text
    assert "not already present in image_prompt" in text


def test_build_input_discourages_unrequested_background_figures():
    text = _build_input(_scene())

    assert "beyond the Subject described below" in text
    assert "unstable, inconsistent rendering" in text


def test_build_input_requires_pre_action_state_zero_in_keyframe():
    text = _build_input(_scene())

    assert "pre-action state of that event" in text
    assert "pin still seated in a grenade" in text
    assert "its physical prerequisite state is absent from image_prompt" in text


def _fake_interaction(output_text: str):
    return SimpleNamespace(output_text=output_text)


def test_run_appends_required_elements_when_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene(required_elements=["이벤트 로고 노출"])
    parsed = Prompts(image_prompt="야간 성벽, 몬스터 무리", video_motion_prompt="슬로우 팬")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(parsed.model_dump_json())
    agent = GeminiPromptAgent(client=client)

    result = agent.run(scene)

    assert result.image_prompt == "야간 성벽, 몬스터 무리, 이벤트 로고 노출"


def test_run_leaves_image_prompt_unmodified_when_no_required_elements(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene(required_elements=[])
    parsed = Prompts(image_prompt="야간 성벽, 몬스터 무리", video_motion_prompt="슬로우 팬")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(parsed.model_dump_json())
    agent = GeminiPromptAgent(client=client)

    result = agent.run(scene)

    assert result.image_prompt == "야간 성벽, 몬스터 무리"


def test_run_passes_feedback_into_built_input(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene()
    parsed = Prompts(image_prompt="p", video_motion_prompt="m")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(parsed.model_dump_json())
    agent = GeminiPromptAgent(client=client)

    agent.run(scene, feedback="fix the lighting")

    _, kwargs = client.interactions.create.call_args
    assert kwargs["input"][0]["text"] == _build_input(scene, feedback="fix the lighting")


def test_run_calls_sdk_with_expected_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene()
    parsed = Prompts(image_prompt="p", video_motion_prompt="m")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(parsed.model_dump_json())
    agent = GeminiPromptAgent(model_name="custom-prompter", client=client)

    agent.run(scene)

    _, kwargs = client.interactions.create.call_args
    assert kwargs["model"] == "custom-prompter"


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene()
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiPromptAgent(client=client)

    with pytest.raises(PromptAgentError):
        agent.run(scene)


def test_run_wraps_malformed_json_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    scene = _scene()
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = GeminiPromptAgent(client=client)

    with pytest.raises(PromptAgentError):
        agent.run(scene)


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiPromptAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.005
    assert agent.estimate_cost() == GeminiPromptAgent.ESTIMATED_COST_USD
