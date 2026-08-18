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


@pytest.mark.asyncio
async def test_poll_task_waits_until_completed_and_extracts_answer():
    responses = iter([
        httpx.Response(200, json={"task": {"id": "task-1", "status": {"state": "TASK_STATE_WORKING"}}}),
        httpx.Response(200, json={
            "task": {
                "id": "task-1",
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "message": {"parts": [{"text": "polled answer"}]},
                },
            },
        }),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/tasks/task-1"
        return next(responses)

    client = A2AClient(transport=httpx.MockTransport(handler), poll_interval=0, poll_timeout=1)
    result = await client.poll_task("http://agent.example/tasks/task-1")

    assert result["status"] == "succeeded"
    assert result["answer"] == "polled answer"


@pytest.mark.asyncio
async def test_poll_task_returns_failed_status_without_waiting_forever():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "task": {"id": "task-2", "status": {"state": "TASK_STATE_FAILED", "message": {"parts": [{"text": "failed"}]}}},
        })

    client = A2AClient(transport=httpx.MockTransport(handler), poll_interval=0, poll_timeout=1)
    result = await client.poll_task("http://agent.example/tasks/task-2")

    assert result["status"] == "failed"
    assert result["answer"] == "failed"
