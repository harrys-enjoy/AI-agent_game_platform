from video_draft_pipeline.schema import ProjectInput
from video_draft_pipeline.agents.planning_agent import PlanningAgent


def test_planning_agent_returns_four_beats_in_order():
    project_input = ProjectInput(
        preset="이벤트", scene_type="인게임", duration_sec=30, brief="Halloween Event"
    )
    narrative = PlanningAgent().run(project_input)

    assert [beat.beat_id for beat in narrative.beats] == [
        "setup",
        "conflict",
        "climax",
        "resolution",
    ]
    assert all("Halloween Event" in beat.description for beat in narrative.beats)


def test_planning_agent_accepts_injected_model_name():
    assert PlanningAgent().planning_model == "gpt-5.4"
    assert PlanningAgent("custom-planner").planning_model == "custom-planner"


def test_planning_agent_estimate_cost_is_zero():
    assert PlanningAgent().estimate_cost() == 0.0
