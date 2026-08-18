from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.auth import A2AAuthError, require_a2a_auth
from video_draft_pipeline.a2a_server.errors import error_response


def _test_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(A2AAuthError)
    def _handle_auth_error(request, exc):
        return error_response("UNAUTHENTICATED", exc.message)

    @app.get("/protected", dependencies=[Depends(require_a2a_auth)])
    def protected():
        return {"ok": True}

    return app


def test_require_a2a_auth_accepts_valid_bearer_and_version(monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "secret-token")
    client = TestClient(_test_app())

    response = client.get(
        "/protected", headers={"Authorization": "Bearer secret-token", "A2A-Version": "1.0"}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_require_a2a_auth_rejects_missing_authorization(monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "secret-token")
    client = TestClient(_test_app())

    response = client.get("/protected", headers={"A2A-Version": "1.0"})

    assert response.status_code == 401
    assert response.json()["error"]["status"] == "UNAUTHENTICATED"


def test_require_a2a_auth_rejects_wrong_bearer_token(monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "secret-token")
    client = TestClient(_test_app())

    response = client.get(
        "/protected", headers={"Authorization": "Bearer wrong-token", "A2A-Version": "1.0"}
    )

    assert response.status_code == 401


def test_require_a2a_auth_rejects_missing_a2a_version_header(monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "secret-token")
    client = TestClient(_test_app())

    response = client.get("/protected", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 401


def test_require_a2a_auth_rejects_when_token_not_configured(monkeypatch):
    monkeypatch.delenv("VIDEO_SERVICE_TOKEN", raising=False)
    client = TestClient(_test_app())

    response = client.get(
        "/protected", headers={"Authorization": "Bearer anything", "A2A-Version": "1.0"}
    )

    assert response.status_code == 401
