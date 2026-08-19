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


def test_agent_card_preserves_http_json_interface_and_security_scheme():
    card = AgentCard.model_validate({
        "name": "game-qna-agent",
        "description": "Game Q&A",
        "url": "https://game.example/message:send",
        "supportedInterfaces": [{
            "url": "https://game.example/message:send",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        }],
        "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
        "skills": [],
    })

    assert card.supported_interfaces[0].protocol_binding == "HTTP+JSON"
    assert card.supported_interfaces[0].protocol_version == "1.0"
    assert card.security_schemes["bearerAuth"]["scheme"] == "bearer"
from app.contracts import AgentCard


def test_agent_card_accepts_interface_only_url():
    card = AgentCard.model_validate({
        "name": "Workmate AI",
        "description": "Workmate agent",
        "supportedInterfaces": [{
            "url": "http://workmate-agent:8001/a2a",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        }],
    })

    assert card.supported_interfaces[0].url.endswith("/a2a")
