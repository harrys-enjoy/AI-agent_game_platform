from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app
from video_draft_pipeline.a2a_server.veo_usage_repository import SQLiteVeoUsageRepository

_AUTH_HEADERS = {"Authorization": "Bearer test-token", "A2A-Version": "1.0"}


def _app_and_client(usage_repository, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_SERVICE_TOKEN", "test-token")
    app = create_app(media_dir=str(tmp_path), usage_repository=usage_repository)
    return TestClient(app)


def test_veo_usage_requires_auth(tmp_path, monkeypatch):
    client = _app_and_client(SQLiteVeoUsageRepository(), tmp_path, monkeypatch)

    response = client.get("/a2a/veo-usage")

    assert response.status_code == 401


def test_veo_usage_returns_zero_used_with_default_limit(tmp_path, monkeypatch):
    monkeypatch.delenv("VEO_DAILY_QUOTA_LIMIT", raising=False)
    client = _app_and_client(SQLiteVeoUsageRepository(), tmp_path, monkeypatch)

    response = client.get("/a2a/veo-usage", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body == {"used": 0, "limit": 10, "resetsAt": None}


def test_veo_usage_reflects_recorded_calls(tmp_path, monkeypatch):
    repo = SQLiteVeoUsageRepository()
    repo.record_call()
    repo.record_call()
    repo.record_call()
    client = _app_and_client(repo, tmp_path, monkeypatch)

    response = client.get("/a2a/veo-usage", headers=_AUTH_HEADERS)

    body = response.json()
    assert body["used"] == 3
    assert body["resetsAt"] is not None


def test_veo_usage_respects_configured_daily_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("VEO_DAILY_QUOTA_LIMIT", "25")
    client = _app_and_client(SQLiteVeoUsageRepository(), tmp_path, monkeypatch)

    response = client.get("/a2a/veo-usage", headers=_AUTH_HEADERS)

    assert response.json()["limit"] == 25
