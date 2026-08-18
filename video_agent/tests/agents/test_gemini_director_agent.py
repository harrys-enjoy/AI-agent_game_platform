from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from video_draft_pipeline.agents.gemini_director_agent import (
    DirectorAgentError,
    DirectorVerdict,
    GeminiDirectorAgent,
)
from video_draft_pipeline.agents.errors import MissingAPIKeyError
from video_draft_pipeline.schema import ConsistencyReview, Scene, Storyboard


def _scene(retry_count: int = 0, max_retries: int = 3) -> Scene:
    return Scene(
        scene_id="scene_01", beat_id="conflict", order=1, duration_sec=6,
        storyboard=Storyboard(camera="pan", subject="x", action="y", setting="z"),
        retry_count=retry_count, max_retries=max_retries,
    )


def _fake_interaction(output_text: str) -> SimpleNamespace:
    return SimpleNamespace(output_text=output_text)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(MissingAPIKeyError):
        GeminiDirectorAgent()


def test_default_model_name_is_gemini_3_6_flash(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiDirectorAgent(client=MagicMock())

    assert agent.model_name == "gemini-3.6-flash"


def test_custom_model_name_stored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiDirectorAgent(model_name="custom-director", client=MagicMock())

    assert agent.model_name == "custom-director"


def test_estimate_cost_returns_fixed_constant(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    agent = GeminiDirectorAgent(client=MagicMock())

    assert agent.estimate_cost() == 0.03
    assert agent.estimate_cost() == GeminiDirectorAgent.ESTIMATED_COST_USD


def test_run_honors_llm_decision_when_under_retry_cap(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    verdict = DirectorVerdict(decision="regenerate", feedback="색감이 어색함")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(verdict.model_dump_json())
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["색감 불일치"])

    decision = agent.run(_scene(retry_count=1, max_retries=3), review)

    assert decision.decision == "regenerate"
    assert decision.feedback == "색감이 어색함"
    assert decision.decided_by == agent.model_name


def test_run_forces_reject_when_regenerate_verdict_hits_retry_cap(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    verdict = DirectorVerdict(decision="regenerate", feedback="한 번 더 시도해볼만함")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(verdict.model_dump_json())
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["색감 불일치"])

    decision = agent.run(_scene(retry_count=3, max_retries=3), review)

    assert decision.decision == "reject"
    assert decision.feedback == "한 번 더 시도해볼만함"


def test_run_honors_accept_verdict_even_when_retries_exhausted(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    verdict = DirectorVerdict(decision="accept", feedback="ok")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(verdict.model_dump_json())
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=True, issues=[])

    decision = agent.run(_scene(retry_count=3, max_retries=3), review)

    assert decision.decision == "accept"
    assert client.interactions.create.called


def test_run_honors_reject_verdict_when_retries_exhausted(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    verdict = DirectorVerdict(decision="reject", feedback="글쎄요")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction(verdict.model_dump_json())
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["issue"])

    decision = agent.run(_scene(retry_count=3, max_retries=3), review)

    assert decision.decision == "reject"


def test_run_wraps_sdk_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.side_effect = RuntimeError("boom")
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["issue"])

    with pytest.raises(DirectorAgentError):
        agent.run(_scene(), review)


def test_run_wraps_malformed_json_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    client = MagicMock()
    client.interactions.create.return_value = _fake_interaction("not valid json")
    agent = GeminiDirectorAgent(client=client)
    review = ConsistencyReview(reviewed_by="gemini-3.6-flash", passed=False, issues=["issue"])

    with pytest.raises(DirectorAgentError):
        agent.run(_scene(), review)
