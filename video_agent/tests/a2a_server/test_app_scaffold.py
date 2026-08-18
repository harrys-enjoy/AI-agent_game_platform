from pathlib import Path

from fastapi.testclient import TestClient

from video_draft_pipeline.a2a_server.app import create_app


def test_agent_card_route_uses_configured_internal_url():
    app = create_app(self_internal_url="http://video-agent:8002")
    client = TestClient(app)

    response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "video-agent"
    assert body["supportedInterfaces"][0]["url"] == "http://video-agent:8002/a2a"


def test_agent_card_route_does_not_require_auth():
    app = create_app(self_internal_url="http://video-agent:8002")
    client = TestClient(app)

    response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200


def test_media_mount_serves_files_from_configured_media_dir(tmp_path):
    (tmp_path / "proj_test.mp4").write_bytes(b"fake-mp4-bytes")
    app = create_app(media_dir=str(tmp_path))
    client = TestClient(app)

    response = client.get("/media/proj_test.mp4")

    assert response.status_code == 200
    assert response.content == b"fake-mp4-bytes"


def test_default_internal_and_media_urls_come_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_INTERNAL_URL", "http://video-agent:9999")
    app = create_app(media_dir=str(tmp_path))
    client = TestClient(app)

    response = client.get("/.well-known/agent-card.json")

    assert response.json()["supportedInterfaces"][0]["url"] == "http://video-agent:9999/a2a"
