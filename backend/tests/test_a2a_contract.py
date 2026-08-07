import json

import httpx
import pytest

from app.a2a_client import A2AClient


@pytest.mark.asyncio
async def test_http_json_request_uses_standard_headers_and_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["content-type"] == "application/a2a+json"
        assert request.headers["authorization"] == "Bearer token-1"
        payload = json.loads(request.read())
        assert payload["message"]["messageId"] == "request-1"
        assert payload["message"]["contextId"] == "context-1"
        assert payload["metadata"]["evidence"] == ["fact"]
        return httpx.Response(200, json={"message": {"parts": [{"text": "ok"}]}})

    client = A2AClient(transport=httpx.MockTransport(handler))
    result = await client.send_message(
        "http://agent.example/message:send",
        {
            "message": "question",
            "request_id": "request-1",
            "context_id": "context-1",
            "evidence": ["fact"],
        },
        headers={"Authorization": "Bearer token-1"},
    )

    assert result["answer"] == "ok"


@pytest.mark.asyncio
async def test_http_json_request_reads_completed_task_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "task": {
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "message": {"parts": [{"text": "completed answer"}]},
                },
            },
        })

    client = A2AClient(transport=httpx.MockTransport(handler))
    result = await client.send_message("http://agent.example/message:send", {"message": "question"})

    assert result["status"] == "succeeded"
    assert result["answer"] == "completed answer"
