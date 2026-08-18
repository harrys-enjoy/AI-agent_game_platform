import json

from video_draft_pipeline.a2a_server.errors import error_response


def test_error_response_invalid_argument_maps_to_400():
    response = error_response("INVALID_ARGUMENT", "message.parts must include text")

    assert response.status_code == 400
    body = json.loads(response.body)
    assert body == {
        "error": {
            "code": 400,
            "status": "INVALID_ARGUMENT",
            "message": "message.parts must include text",
        }
    }


def test_error_response_not_found_maps_to_404():
    response = error_response("NOT_FOUND", "Unknown task: task_abc")

    assert response.status_code == 404
    body = json.loads(response.body)
    assert body["error"]["status"] == "NOT_FOUND"


def test_error_response_unavailable_maps_to_503():
    response = error_response("UNAVAILABLE", "No Gemini API key configured")

    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["error"]["code"] == 503


def test_error_response_unauthenticated_maps_to_401():
    response = error_response("UNAUTHENTICATED", "Invalid or missing Authorization Bearer token")

    assert response.status_code == 401
    body = json.loads(response.body)
    assert body["error"]["status"] == "UNAUTHENTICATED"


def test_error_response_permission_denied_maps_to_403():
    response = error_response("PERMISSION_DENIED", "Not allowed")

    assert response.status_code == 403
    body = json.loads(response.body)
    assert body["error"]["status"] == "PERMISSION_DENIED"
