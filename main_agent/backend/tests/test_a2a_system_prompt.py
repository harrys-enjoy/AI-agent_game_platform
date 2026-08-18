import httpx
import pytest

from app.a2a_client import A2AClient


@pytest.mark.asyncio
async def test_http_json_message_forwards_main_system_prompt():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert '"systemPrompt":"main-agent-policy"' in body
        return httpx.Response(200, json={"message": {"parts": [{"text": "ok"}]}})

    client = A2AClient(transport=httpx.MockTransport(handler))
    result = await client.send_message(
        "http://game-qna-agent:3000/message:send",
        {"message": "question", "system_prompt": "main-agent-policy"},
    )
    assert result["answer"] == "ok"
