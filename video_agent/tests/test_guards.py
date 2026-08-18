import pytest

from video_draft_pipeline.schema import Scene, Storyboard
from video_draft_pipeline.guards import (
    duration_guard,
    budget_guard,
    DurationExceededError,
    BudgetExceededError,
)


def _scene(duration_sec: float) -> Scene:
    return Scene(
        scene_id="scene_01",
        beat_id="setup",
        order=1,
        duration_sec=duration_sec,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
    )


def test_duration_guard_passes_under_cap():
    scenes = [_scene(10), _scene(10), _scene(10)]
    assert duration_guard(scenes, max_duration_sec=30) == 30


def test_duration_guard_raises_over_cap():
    scenes = [_scene(20), _scene(20)]
    with pytest.raises(DurationExceededError):
        duration_guard(scenes, max_duration_sec=30)


def test_budget_guard_passes_under_cap():
    assert budget_guard(current_cost_usd=2.0, additional_cost_usd=1.0, max_budget_usd=5.0) == 3.0


def test_budget_guard_raises_over_cap():
    with pytest.raises(BudgetExceededError):
        budget_guard(current_cost_usd=4.5, additional_cost_usd=1.0, max_budget_usd=5.0)


def test_budget_guard_rejects_negative_additional_cost():
    with pytest.raises(BudgetExceededError):
        budget_guard(current_cost_usd=4.9, additional_cost_usd=-16.0, max_budget_usd=5.0)
