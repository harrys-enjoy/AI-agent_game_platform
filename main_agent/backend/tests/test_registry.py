import httpx
import pytest

from app.registry import AgentRegistry


@pytest.mark.asyncio
async def test_registry_marks_failed_card_unavailable():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    registry = AgentRegistry(transport=transport)
    registry.register("workmate-agent", "http://workmate-agent:8001")

    cards = await registry.refresh()

    assert cards == {}
    assert registry.status("workmate-agent").available is False


@pytest.mark.asyncio
async def test_registry_selects_http_json_one_point_zero_interface():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "name": "workmate-agent",
            "description": "Workmate",
            "url": "http://workmate-agent:8001/a2a",
            "supportedInterfaces": [{
                "url": "http://workmate-agent:8001/message:send",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            }],
            "skills": [],
        })

    registry = AgentRegistry(transport=httpx.MockTransport(handler))
    registry.register("workmate-agent", "http://workmate-agent:8001")

    cards = await registry.refresh()

    assert cards["workmate-agent"].url.endswith("/message:send")


def test_registry_loads_agents_and_tokens_from_environment():
    registry = AgentRegistry.from_environment({
        "AGENT_REGISTRY": "workmate-agent, game-qna-agent",
        "WORKMATE_AGENT_URL": "http://workmate-agent:8001",
        "WORKMATE_AGENT_TOKEN": "work-token",
        "GAME_QNA_AGENT_URL": "http://game-qna-agent:3000",
        "GAME_QNA_AGENT_TOKEN": "game-token",
    })

    assert registry.config("workmate-agent").base_url == "http://workmate-agent:8001"
    assert registry.config("workmate-agent").token == "work-token"
    assert registry.headers("game-qna-agent") == {"Authorization": "Bearer game-token"}


def test_registry_keeps_legacy_game_url_fallback():
    registry = AgentRegistry.from_environment({
        "GAME_QA_AGENT_URL": "http://legacy-game:3010/message:send",
    })

    assert registry.config("game-qna-agent").base_url == "http://legacy-game:3010"


def test_registry_reads_service_token_with_endpoint_url():
    registry = AgentRegistry.from_environment({
        "AGENT_REGISTRY": "workmate-agent",
        "WORKMATE_AGENT_URL": "http://workmate-agent:8001/a2a",
        "WORKMATE_SERVICE_TOKEN": "service-token",
    })

    assert registry.config("workmate-agent").base_url == "http://workmate-agent:8001"
    assert registry.headers("workmate-agent") == {"Authorization": "Bearer service-token"}
