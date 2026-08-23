import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as kosa_main  # noqa: E402


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def client():
    return TestClient(kosa_main.app)


def test_delete_rejects_name_without_prefix(client, monkeypatch):
    calls = []
    monkeypatch.setattr(kosa_main, "_run_docker", lambda args: calls.append(args) or FakeCompleted())

    res = client.delete("/api/deployments/some-other-container")

    assert res.status_code == 400
    assert calls == []  # never touches docker for an unprefixed name


def test_delete_rejects_running_container(client, monkeypatch):
    def fake_run_docker(args):
        assert args[0] == "inspect"
        return FakeCompleted(stdout="true\t\n")

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo")

    assert res.status_code == 409


def test_delete_404s_when_container_missing(client, monkeypatch):
    monkeypatch.setattr(
        kosa_main, "_run_docker", lambda args: FakeCompleted(returncode=1, stderr="No such object")
    )

    res = client.delete("/api/deployments/kosa-deploy-owner-repo")

    assert res.status_code == 404


def test_delete_removes_single_container_when_no_compose_label(client, monkeypatch):
    calls = []

    def fake_run_docker(args):
        calls.append(args)
        if args[0] == "inspect":
            return FakeCompleted(stdout="false\t\n")
        return FakeCompleted(returncode=0)

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo")

    assert res.status_code == 200
    assert res.json() == {"status": "deleted", "name": "kosa-deploy-owner-repo"}
    assert calls[1] == ["rm", "kosa-deploy-owner-repo"]


def test_delete_removes_whole_compose_project_when_label_present(client, monkeypatch):
    calls = []

    def fake_run_docker(args):
        calls.append(args)
        if args[0] == "inspect":
            return FakeCompleted(stdout="false\tkosa-deploy-owner-repo\n")
        if args[0] == "ps":
            return FakeCompleted(stdout="")  # no siblings still running
        return FakeCompleted(returncode=0)

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo-mysql-1")

    assert res.status_code == 200
    assert calls[1] == ["ps", "--filter", "label=com.docker.compose.project=kosa-deploy-owner-repo", "--format", "{{.Names}}"]
    assert calls[2] == ["compose", "-p", "kosa-deploy-owner-repo", "down"]


def test_delete_rejects_when_compose_sibling_still_running(client, monkeypatch):
    """Clicked container is STOPPED, but a sibling in the same compose project is still
    RUNNING — `down` would take that sibling out too, which breaks the STOPPED-only
    guarantee. Caught during manual browser verification (2026-08-23): deleting a
    crashed `app` container silently killed the still-running `mysql` sibling."""
    calls = []

    def fake_run_docker(args):
        calls.append(args)
        if args[0] == "inspect":
            return FakeCompleted(stdout="false\tkosa-deploy-owner-repo\n")
        if args[0] == "ps":
            return FakeCompleted(stdout="kosa-deploy-owner-repo-mysql-1\n")
        return FakeCompleted(returncode=0)

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo-app-1")

    assert res.status_code == 409
    assert not any(c[0] == "compose" for c in calls)  # never actually tears anything down


def test_delete_returns_500_when_removal_fails(client, monkeypatch):
    def fake_run_docker(args):
        if args[0] == "inspect":
            return FakeCompleted(stdout="false\t\n")
        return FakeCompleted(returncode=1, stderr="permission denied")

    monkeypatch.setattr(kosa_main, "_run_docker", fake_run_docker)

    res = client.delete("/api/deployments/kosa-deploy-owner-repo")

    assert res.status_code == 500
    assert "permission denied" in res.json()["detail"]
