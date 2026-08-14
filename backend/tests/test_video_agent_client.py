import httpx
import pytest

from app.errors import A2AError
from app.registry import AgentRegistry
from app.video_agent_client import cancel_task, get_task, send_message


def _registry():
    registry = AgentRegistry()
    registry.register("video-agent", "http://video-agent:8002", token="secret-token")
    return registry


@pytest.mark.asyncio
async def test_send_message_posts_a2a_envelope_with_fresh_message_id(monkeypatch):
    seen = {}

    async def fake_post(self, url, *, json=None, headers=None):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_SUBMITTED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await send_message(_registry(), "할로윈 이벤트 영상 15초로 만들어줘")

    assert seen["url"] == "http://video-agent:8002/a2a/message:send"
    assert seen["json"]["message"]["role"] == "ROLE_USER"
    assert seen["json"]["message"]["parts"] == [{"text": "할로윈 이벤트 영상 15초로 만들어줘"}]
    assert seen["headers"]["Authorization"] == "Bearer secret-token"
    assert seen["headers"]["A2A-Version"] == "1.0"
    assert len(seen["json"]["message"]["messageId"]) > 0
    assert result["task"]["id"] == "task_1"


@pytest.mark.asyncio
async def test_send_message_uses_a_fresh_message_id_every_call(monkeypatch):
    seen_ids = []

    async def fake_post(self, url, *, json=None, headers=None):
        seen_ids.append(json["message"]["messageId"])
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_SUBMITTED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    registry = _registry()
    await send_message(registry, "브리프 1")
    await send_message(registry, "브리프 2")

    assert seen_ids[0] != seen_ids[1]


@pytest.mark.asyncio
async def test_get_task_sends_bearer_and_a2a_version_headers(monkeypatch):
    seen = {}

    async def fake_get(self, url, *, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_WORKING"}}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await get_task(_registry(), "task_1")

    assert seen["url"] == "http://video-agent:8002/a2a/tasks/task_1"
    assert seen["headers"]["Authorization"] == "Bearer secret-token"
    assert seen["headers"]["A2A-Version"] == "1.0"
    assert result["task"]["status"]["state"] == "TASK_STATE_WORKING"


@pytest.mark.asyncio
async def test_cancel_task_posts_to_cancel_endpoint(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        assert url == "http://video-agent:8002/a2a/tasks/task_1:cancel"
        assert headers["A2A-Version"] == "1.0"
        return httpx.Response(
            200,
            json={"task": {"id": "task_1", "contextId": "ctx_1", "status": {"state": "TASK_STATE_CANCELED"}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await cancel_task(_registry(), "task_1")

    assert result["task"]["status"]["state"] == "TASK_STATE_CANCELED"


@pytest.mark.asyncio
async def test_get_task_raises_a2a_error_on_error_envelope(monkeypatch):
    async def fake_get(self, url, *, headers=None):
        return httpx.Response(
            404,
            json={"error": {"code": 404, "status": "NOT_FOUND", "message": "Unknown task: task_x"}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(A2AError) as exc_info:
        await get_task(_registry(), "task_x")

    assert exc_info.value.http_status == 404
    assert "Unknown task: task_x" in exc_info.value.message


@pytest.mark.asyncio
async def test_send_message_raises_runtime_error_when_unreachable(monkeypatch):
    async def fake_post(self, url, *, json=None, headers=None):
        raise httpx.ConnectError("Connection refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(httpx.ConnectError):
        await send_message(_registry(), "브리프")


@pytest.mark.asyncio
async def test_get_task_raises_runtime_error_on_non_json_body(monkeypatch):
    async def fake_get(self, url, *, headers=None):
        return httpx.Response(500, text="internal server error", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(RuntimeError, match="video-agent HTTP 500"):
        await get_task(_registry(), "task_1")
