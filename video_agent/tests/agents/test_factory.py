import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.factory import build_real_agents
from video_draft_pipeline.agents.gemini_director_agent import DirectorVerdict
from video_draft_pipeline.agents.gemini_storyboard_agent import SceneDraft, StoryboardDraft
from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.config import ModelConfig
from video_draft_pipeline.orchestrator import run_pipeline
from video_draft_pipeline.schema import Beat, Narrative, ProjectInput, Prompts


def test_missing_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        build_real_agents(output_dir=tmp_path / "media")


def test_explicit_api_key_threaded_to_all_agents(tmp_path):
    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key",
        gemini_client=MagicMock(),
        output_dir=tmp_path / "media",
    )

    assert agents["planning_agent"].api_key == "explicit-gemini-key"
    assert agents["storyboard_agent"].api_key == "explicit-gemini-key"
    assert agents["prompt_agent"].api_key == "explicit-gemini-key"
    assert agents["image_agent"].api_key == "explicit-gemini-key"
    assert agents["review_agent"].api_key == "explicit-gemini-key"
    assert agents["director_agent"].api_key == "explicit-gemini-key"
    assert agents["image_edit_agent"].api_key == "explicit-gemini-key"


def test_returns_exactly_the_seven_expected_keys(tmp_path):
    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key", gemini_client=MagicMock(), output_dir=tmp_path / "media"
    )

    assert set(agents.keys()) == {
        "planning_agent", "storyboard_agent", "prompt_agent", "image_agent",
        "review_agent", "director_agent", "image_edit_agent",
    }


def test_custom_model_config_threaded_to_each_agent(tmp_path):
    model_config = ModelConfig(
        planning_model="custom-planner", storyboard_model="custom-storyboarder",
        prompt_model="custom-prompter", image_model="custom-imager",
        review_model="custom-reviewer", director_model="custom-director",
        image_edit_model="custom-image-editor",
    )

    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key", gemini_client=MagicMock(),
        output_dir=tmp_path / "media", model_config=model_config,
    )

    assert agents["planning_agent"].model_name == "custom-planner"
    assert agents["storyboard_agent"].model_name == "custom-storyboarder"
    assert agents["prompt_agent"].model_name == "custom-prompter"
    assert agents["image_agent"].model_name == "custom-imager"
    assert agents["review_agent"].model_name == "custom-reviewer"
    assert agents["director_agent"].model_name == "custom-director"
    assert agents["image_edit_agent"].model_name == "custom-image-editor"


def test_output_dir_threaded_to_image_agents(tmp_path):
    custom_dir = tmp_path / "custom-media"

    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key", gemini_client=MagicMock(), output_dir=custom_dir
    )

    assert agents["image_agent"].output_dir == custom_dir
    assert agents["image_edit_agent"].output_dir == custom_dir
    assert custom_dir.is_dir()


def test_log_path_threaded_to_all_agents(tmp_path):
    log_path = tmp_path / "agent_log.jsonl"

    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key",
        gemini_client=MagicMock(),
        output_dir=tmp_path / "media",
        log_path=log_path,
    )

    for name, agent in agents.items():
        assert agent._log_path == log_path, f"{name} did not receive log_path"


def test_log_path_defaults_to_none(tmp_path):
    agents = build_real_agents(
        gemini_api_key="explicit-gemini-key", gemini_client=MagicMock(), output_dir=tmp_path / "media"
    )

    for name, agent in agents.items():
        assert agent._log_path is None, f"{name} should default to no logging"


def test_build_real_agents_output_works_with_run_pipeline(tmp_path):
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )
    draft = StoryboardDraft(
        scenes=[
            SceneDraft(
                beat_id=beat_id, camera="cam", subject="subj", action="act", setting="set",
                required_elements=[], duration_weight=1,
            )
            for beat_id in ("setup", "conflict", "climax", "resolution")
        ]
    )
    prompts = Prompts(image_prompt="a haunted castle", video_motion_prompt="pan")
    director_verdict = DirectorVerdict(decision="accept", feedback="ok")

    def fake_create(*, model, input, **kwargs):
        response_format = kwargs.get("response_format")
        if response_format is None:
            image_data = base64.b64encode(b"fake-image-bytes").decode("utf-8")
            return SimpleNamespace(output_image=SimpleNamespace(data=image_data))
        schema_title = response_format["schema"]["title"]
        if schema_title == "Narrative":
            return SimpleNamespace(output_text=narrative.model_dump_json())
        if schema_title == "StoryboardDraft":
            return SimpleNamespace(output_text=draft.model_dump_json())
        if schema_title == "Prompts":
            return SimpleNamespace(output_text=prompts.model_dump_json())
        if schema_title == "ReviewVerdict":
            return SimpleNamespace(output_text='{"passed": true, "issues": []}')
        if schema_title == "DirectorVerdict":
            return SimpleNamespace(output_text=director_verdict.model_dump_json())
        raise AssertionError(f"unexpected response_format schema: {schema_title}")

    shared_gemini_client = MagicMock()
    shared_gemini_client.interactions.create.side_effect = fake_create

    project_input = ProjectInput(preset="이벤트", scene_type="인게임", duration_sec=10, brief="Halloween Event")

    project = run_pipeline(
        project_input,
        **build_real_agents(
            gemini_api_key="test-key", gemini_client=shared_gemini_client, output_dir=tmp_path / "media"
        ),
    )

    assert len(project.scenes) == 4
    assert project.scenes[0].render is not None
    assert project.scenes[0].candidates[-1].consistency_review.passed is True
    assert project.scenes[0].candidates[-1].director_decision.decision == "accept"
