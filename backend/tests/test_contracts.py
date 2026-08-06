import pytest
from pydantic import ValidationError

from app.contracts import AgentCard, TaskRecord


def test_agent_card_preserves_declared_skills():
    card = AgentCard(
        name="workmate-agent",
        description="업무지원 Agent",
        url="http://workmate-agent:8001/a2a",
        skills=[{"id": "daily_briefing", "name": "일일 브리핑"}],
        streaming=True,
    )

    assert card.skills[0].id == "daily_briefing"


def test_task_rejects_unknown_status():
    with pytest.raises(ValidationError):
        TaskRecord(task_id="t1", request="x", selected_agents=[], status="unknown")
