import pytest

from video_draft_pipeline.render_backends.stub_backend import StubRenderBackend
from video_draft_pipeline.schema import Candidate


def _candidate() -> Candidate:
    return Candidate(candidate_id="c1", image_url="stub://x.png", generated_by="gpt-image-2")


def test_rejects_unknown_tier():
    with pytest.raises(ValueError):
        StubRenderBackend(tier="veo-9000")


def test_render_returns_stub_clip_url():
    backend = StubRenderBackend(tier="veo-3.1-fast")

    result = backend.render(_candidate(), motion_prompt="pan left", duration_sec=6.0)

    assert result.backend == "veo-3.1-fast"
    assert result.status == "done"
    assert result.clip_url == "stub://veo/c1.mp4"


@pytest.mark.parametrize(
    "tier,duration_sec,expected",
    [
        ("veo-3.1-lite", 6.0, 0.30),
        ("veo-3.1-fast", 6.0, 0.60),
        ("veo-3.1-standard", 6.0, 2.40),
    ],
)
def test_estimate_cost_per_tier(tier, duration_sec, expected):
    backend = StubRenderBackend(tier=tier)

    assert backend.estimate_cost(duration_sec) == expected


def test_estimate_cost_does_not_round_duration():
    backend = StubRenderBackend(tier="veo-3.1-fast")

    assert backend.estimate_cost(7.3) == 0.73


def test_render_cost_matches_estimate_cost_for_arbitrary_duration():
    backend = StubRenderBackend(tier="veo-3.1-fast")

    result = backend.render(_candidate(), motion_prompt="pan left", duration_sec=7.3)

    assert result.cost_usd == 0.73
