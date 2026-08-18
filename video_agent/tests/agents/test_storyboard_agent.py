from video_draft_pipeline.schema import ProjectInput, Narrative, Beat
from video_draft_pipeline.agents.storyboard_agent import StoryboardAgent


def test_storyboard_agent_splits_duration_evenly_with_remainder_on_last_scene():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )

    scenes = StoryboardAgent().run(narrative, project_input)

    assert len(scenes) == 4
    assert sum(scene.duration_sec for scene in scenes) == 30
    assert [scene.order for scene in scenes] == [1, 2, 3, 4]
    assert [scene.beat_id for scene in scenes] == [
        "setup",
        "conflict",
        "climax",
        "resolution",
    ]


def test_storyboard_agent_puts_brand_requirements_on_resolution_scene():
    project_input = ProjectInput(
        preset="이벤트",
        scene_type="인게임",
        duration_sec=20,
        brief="Halloween Event",
        brand_requirements=["이벤트 로고 노출"],
    )
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )

    scenes = StoryboardAgent().run(narrative, project_input)

    assert scenes[0].storyboard.required_elements == []
    assert scenes[1].storyboard.required_elements == ["이벤트 로고 노출"]


def test_storyboard_agent_handles_uneven_division_with_float_duration():
    """Test that uneven duration splits work correctly with float division."""
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Test Event"
    )
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="resolution", description="d3", tone="hype"),
        ]
    )

    scenes = StoryboardAgent().run(narrative, project_input)

    assert len(scenes) == 3
    assert abs(sum(scene.duration_sec for scene in scenes) - 10) < 1e-9  # exact sum
    assert all(scene.duration_sec > 0 for scene in scenes)  # all positive


def test_storyboard_agent_handles_short_duration_many_beats():
    """Test that short durations with many beats don't crash (previously caused ZeroDivisionError)."""
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=3, brief="Short Event"
    )
    narrative = Narrative(
        beats=[
            Beat(beat_id="setup", description="d1", tone="calm"),
            Beat(beat_id="conflict", description="d2", tone="tense"),
            Beat(beat_id="climax", description="d3", tone="epic"),
            Beat(beat_id="resolution", description="d4", tone="hype"),
        ]
    )

    scenes = StoryboardAgent().run(narrative, project_input)

    assert len(scenes) == 4
    assert abs(sum(scene.duration_sec for scene in scenes) - 3) < 1e-9  # exact sum
    assert all(scene.duration_sec > 0 for scene in scenes)  # all positive


def test_storyboard_agent_rejects_empty_beats():
    """Test that empty beat list raises ValueError."""
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=10, brief="Test Event"
    )
    narrative = Narrative(beats=[])

    try:
        StoryboardAgent().run(narrative, project_input)
        assert False, "Expected ValueError for empty beats"
    except ValueError as e:
        assert "at least one beat" in str(e)


def test_storyboard_agent_accepts_injected_model_name():
    assert StoryboardAgent().storyboard_model == "gpt-5.4"
    assert StoryboardAgent("custom-storyboarder").storyboard_model == "custom-storyboarder"


def test_storyboard_agent_estimate_cost_is_zero():
    assert StoryboardAgent().estimate_cost() == 0.0
