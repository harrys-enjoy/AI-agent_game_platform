import httpx
import pytest

from app.a2a_client import A2AClient
from app.errors import A2AError


@pytest.mark.asyncio
async def test_catalog_a2a_error_preserves_status_code_and_request_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={
            "error": {
                "code": 401,
                "status": "UNAUTHENTICATED",
                "message": "Bearer token required",
                "requestId": "req-401",
            },
        })

    client = A2AClient(transport=httpx.MockTransport(handler))

    with pytest.raises(A2AError) as raised:
        await client.send_message("http://agent.example/message:send", {"message": "question"})

    assert raised.value.http_status == 401
    assert raised.value.status == "UNAUTHENTICATED"
    assert raised.value.request_id == "req-401"
    assert raised.value.to_dict()["error"]["code"] == 401


def test_catalog_error_statuses_map_to_main_http_statuses():
    assert A2AError.from_payload({"error": {"status": "INVALID_ARGUMENT", "message": "bad"}}, 500).http_status == 400
    assert A2AError.from_payload({"error": {"status": "NOT_FOUND", "message": "missing"}}, 500).http_status == 404
    assert A2AError.from_payload({"error": {"status": "UNAVAILABLE", "message": "down"}}, 500).http_status == 503
    assert A2AError.from_payload({"error": {"status": "INTERNAL", "message": "broken"}}, 500).http_status == 502
