import json

import httpx
import pytest

from app.a2a_client import A2AClient


@pytest.mark.asyncio
async def test_get_agent_card_and_send_message():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(
                200,
                json={
                    "name": "workmate-agent",
                    "description": "업무지원 Agent",
                    "url": "http://workmate-agent:8001/a2a",
                    "skills": [{"id": "daily_briefing", "name": "일일 브리핑"}],
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"status": "succeeded"}})

    client = A2AClient(transport=httpx.MockTransport(handler))
    card = await client.get_agent_card("http://workmate-agent:8001")
    result = await client.send_message(card.url, {"message": "오늘 브리핑"})

    assert card.name == "workmate-agent"
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_send_message_supports_http_json_agent_card_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/message:send"
        body = request.read().decode()
        assert '"ROLE_USER"' in body
        return httpx.Response(200, json={"message": {"parts": [{"text": "게임 답변"}]}})

    client = A2AClient(transport=httpx.MockTransport(handler))
    result = await client.send_message("http://game-qa-agent:3000/message:send", {"message": "세계관 질문"})

    assert result["status"] == "succeeded"
    assert result["answer"] == "게임 답변"


@pytest.mark.asyncio
async def test_send_message_builds_workmate_http_json_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/a2a/message:send"
        assert request.headers["A2A-Version"] == "1.0"
        assert request.headers["Authorization"] == "Bearer workmate-token"
        payload = json.loads(request.content)
        assert payload["message"]["parts"][0]["data"] == {
            "skill_id": "daily_briefing",
            "message": "오늘 업무",
        }
        return httpx.Response(200, json={"message": {"parts": [{"text": "완료"}]}})

    client = A2AClient(transport=httpx.MockTransport(handler))
    result = await client.send_message(
        "http://workmate-agent:8001/a2a",
        {"message": "오늘 업무", "skill_id": "daily_briefing"},
        headers={"Authorization": "Bearer workmate-token"},
    )

    assert result["status"] == "succeeded"
    assert result["answer"] == "완료"
