import os
import socket
import stat
import time

import pytest

from graph.deploy_trigger import (
    DEFAULT_CONTAINER_PORT,
    DEPLOY_ERROR_DOCKERFILE_NOT_EXIST,
    MAX_CONCURRENT_DEPLOYS,
    _acquire_lock,
    _clone_dir,
    _clone_repo,
    _compose_services_running,
    _docker_path,
    _find_compose_file,
    _find_free_port,
    _host_ports_in_use,
    _lock_file,
    _parse_exposed_port,
    _release_lock,
    _resolve_container_port,
    _slot_name,
    _tail,
    deploy_trigger_node,
)


@pytest.fixture(autouse=True)
def _reset_deploy_locks():
    """워커 슬롯 락을 매 테스트 전후로 비워, deploy_trigger_node가 항상 워커 0을 잡게 한다."""
    for worker in range(MAX_CONCURRENT_DEPLOYS):
        _lock_file(worker).unlink(missing_ok=True)
    yield
    for worker in range(MAX_CONCURRENT_DEPLOYS):
        _lock_file(worker).unlink(missing_ok=True)


def test_clone_repo_removes_existing_readonly_dir_before_cloning(tmp_path):
    stale = tmp_path / "current"
    stale.mkdir()
    readonly_file = stale / "objects.pack"
    readonly_file.write_text("stale data")
    readonly_file.chmod(stat.S_IREAD)

    def fake_run(cmd, **kwargs):
        return FakeCompleted(returncode=0)

    assert _clone_repo("owner/name", "beta", fake_run, stale) is None
    assert not stale.exists()


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRepo:
    default_branch = "beta"


class FakeGithub:
    def get_repo(self, name):
        return FakeRepo()


def _make_run(overrides: dict):
    """cmd의 서브커맨드(cmd[1])를 키로 하는 결과 매핑을 받아 가짜 run을 만든다.

    clone이 성공하면 실제 git clone처럼 Dockerfile을 만들어둔다 — deploy_trigger_node가
    빌드 전에 Dockerfile 존재를 확인하기 때문에 필요하다. 어느 워커 슬롯을 잡을지는
    테스트가 미리 점유해둔 슬롯 수에 따라 달라지므로, 모든 슬롯 디렉터리에 만들어둔다.
    """

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        result = overrides.get(key, FakeCompleted(returncode=0))
        if key == "clone" and result.returncode == 0:
            for worker in range(MAX_CONCURRENT_DEPLOYS):
                clone_dir = _clone_dir(worker)
                clone_dir.mkdir(parents=True, exist_ok=True)
                (clone_dir / "Dockerfile").write_text("FROM scratch\n")
        return result

    return fake_run


def _fake_run_reports_no_ports_in_use(cmd, **kwargs):
    return FakeCompleted(stdout="")


def test_find_free_port_returns_first_available():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 40000))
        port = _find_free_port("docker", _fake_run_reports_no_ports_in_use, range(40000, 40003))

    assert port in (40001, 40002)


def test_find_free_port_returns_none_when_range_exhausted():
    sockets = []
    try:
        for p in range(40000, 40003):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", p))
            sockets.append(s)

        assert _find_free_port("docker", _fake_run_reports_no_ports_in_use, range(40000, 40003)) is None
    finally:
        for s in sockets:
            s.close()


def test_find_free_port_skips_ports_docker_ps_reports_busy():
    """dev-agent 자신의 네트워크 네임스페이스에서 소켓 bind는 성공해도(호스트의 실제
    사용 현황을 못 봄), docker ps가 이미 그 포트를 쓰고 있다고 보고하면 건너뛴다 —
    main-agent가 호스트 8000을 쓰는데 dev-agent 안에서는 비어있는 것처럼 보여 실제로
    포트 충돌이 났던 버그를 고정하는 회귀 테스트."""
    def fake_run(cmd, **kwargs):
        assert cmd[1] == "ps"
        return FakeCompleted(stdout="0.0.0.0:40000->8000/tcp, :::40000->8000/tcp\n")

    port = _find_free_port("docker", fake_run, range(40000, 40003))

    assert port == 40001


def test_host_ports_in_use_parses_docker_ps_output():
    def fake_run(cmd, **kwargs):
        return FakeCompleted(stdout=(
            "0.0.0.0:8000->8000/tcp, :::8000->8000/tcp\n"
            "0.0.0.0:8004->8000/tcp\n"
            "8003/tcp\n"
        ))

    assert _host_ports_in_use("docker", fake_run) == {8000, 8004}


def test_host_ports_in_use_returns_empty_set_on_docker_ps_failure():
    def fake_run(cmd, **kwargs):
        return FakeCompleted(returncode=1, stderr="daemon not running")

    assert _host_ports_in_use("docker", fake_run) == set()


def test_tail_returns_last_n_lines():
    text = "\n".join(f"line{i}" for i in range(30))

    result = _tail(text, 5)

    assert result == "\n".join(f"line{i}" for i in range(25, 30))


def test_tail_returns_all_lines_when_shorter_than_n():
    assert _tail("a\nb", 20) == "a\nb"


def test_clone_repo_returns_none_on_success(tmp_path):
    def fake_run(cmd, **kwargs):
        return FakeCompleted(returncode=0)

    assert _clone_repo("owner/name", "beta", fake_run, tmp_path / "current") is None


def test_clone_repo_includes_submodules(tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompleted(returncode=0)

    _clone_repo("owner/name", "beta", fake_run, tmp_path / "current")

    assert "--recurse-submodules" in captured["cmd"]
    assert "--shallow-submodules" in captured["cmd"]


def test_clone_repo_returns_message_with_stderr_on_failure(tmp_path):
    def fake_run(cmd, **kwargs):
        return FakeCompleted(returncode=1, stderr="fatal: Remote branch beta not found")

    result = _clone_repo("owner/name", "beta", fake_run, tmp_path / "current")

    assert "beta" in result
    assert "fatal: Remote branch beta not found" in result


def test_deploy_trigger_node_reports_docker_not_running_without_touching_github(monkeypatch):
    def explode():
        raise AssertionError("Docker가 꺼져 있으면 GitHub 클라이언트를 만들면 안 된다")

    monkeypatch.setattr("graph.deploy_trigger.get_github_client", explode)

    def fake_run(cmd, **kwargs):
        return FakeCompleted(returncode=1, stderr="Cannot connect to the Docker daemon")

    result = deploy_trigger_node({"repo": "owner/name"}, run=fake_run)

    assert "Docker Desktop" in result["results"]["deploy"]


def test_deploy_trigger_node_reports_build_failure():
    fake_run = _make_run(
        {
            "info": FakeCompleted(returncode=0),
            "clone": FakeCompleted(returncode=0),
            "build": FakeCompleted(returncode=1, stderr="ERROR: failed to solve"),
        }
    )

    result = deploy_trigger_node({"repo": "owner/name"}, gh_client=FakeGithub(), run=fake_run)

    assert "빌드에 실패" in result["results"]["deploy"]
    assert "ERROR: failed to solve" in result["results"]["deploy"]


def test_deploy_trigger_node_reports_no_free_port():
    fake_run = _make_run(
        {
            "info": FakeCompleted(returncode=0),
            "clone": FakeCompleted(returncode=0),
            "build": FakeCompleted(returncode=0),
        }
    )

    result = deploy_trigger_node(
        {"repo": "owner/name"}, gh_client=FakeGithub(), run=fake_run, port_range=range(0, 0)
    )

    assert "포트를 찾지 못했습니다" in result["results"]["deploy"]


def test_deploy_trigger_node_reports_container_start_failure():
    fake_run = _make_run(
        {
            "info": FakeCompleted(returncode=0),
            "clone": FakeCompleted(returncode=0),
            "build": FakeCompleted(returncode=0),
            "run": FakeCompleted(
                returncode=1, stderr="Bind for 0.0.0.0:8000 failed: port is already allocated"
            ),
        }
    )

    result = deploy_trigger_node({"repo": "owner/name"}, gh_client=FakeGithub(), run=fake_run)

    assert "시작되지 않았습니다" in result["results"]["deploy"]
    assert "port is already allocated" in result["results"]["deploy"]


def test_deploy_trigger_node_reports_health_check_timeout():
    fake_run = _make_run(
        {
            "info": FakeCompleted(returncode=0),
            "clone": FakeCompleted(returncode=0),
            "build": FakeCompleted(returncode=0),
            "run": FakeCompleted(returncode=0),
            "logs": FakeCompleted(stdout="app crashed on boot"),
        }
    )

    result = deploy_trigger_node(
        {"repo": "owner/name"},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: False,
    )

    assert "응답이 없습니다" in result["results"]["deploy"]
    assert "app crashed on boot" in result["results"]["deploy"]


def test_deploy_trigger_node_health_checks_via_host_docker_internal():
    """dev-agent 자신의 네트워크 네임스페이스에서 "localhost"는 호스트가 아니라 dev-agent
    자신을 가리킨다 — 방금 배포한 컨테이너가 호스트에 게시한 포트를 "localhost"로 찔러보면
    항상 응답이 없다고(연결 자체가 안 됨) 오판한다. Docker Desktop이 컨테이너 안에서 호스트를
    가리키도록 제공하는 host.docker.internal로 헬스체크해야 한다 — 실제로 whoami를 배포했을 때
    호스트에서는 정상 응답했는데 이 헬스체크가 "응답 없음"으로 오판했던 버그의 회귀 테스트."""
    fake_run = _make_run(
        {
            "info": FakeCompleted(returncode=0),
            "clone": FakeCompleted(returncode=0),
            "build": FakeCompleted(returncode=0),
            "run": FakeCompleted(returncode=0),
        }
    )
    captured = {}

    def spy_health_check(url):
        captured["url"] = url
        return True

    result = deploy_trigger_node(
        {"repo": "owner/name"},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=spy_health_check,
    )

    assert captured["url"].startswith("http://host.docker.internal:")
    # 유저에게 보여주는 성공 메시지는 그대로 localhost여야 한다 — 유저는 실제 호스트에서
    # 브라우저로 접속하는 거라 host.docker.internal은 유저 입장에선 안 통한다.
    assert "http://localhost:" in result["results"]["deploy"]
    assert "host.docker.internal" not in result["results"]["deploy"]


def test_docker_path_adds_fallback_dir_to_path(monkeypatch, tmp_path):
    fake_docker = tmp_path / "docker.exe"
    fake_docker.touch()
    monkeypatch.setattr("graph.deploy_trigger.shutil.which", lambda name: None)
    monkeypatch.setattr("graph.deploy_trigger.Path", lambda *_: fake_docker)
    monkeypatch.setenv("PATH", r"C:\some\other\dir")

    result = _docker_path()

    assert result == str(fake_docker)
    assert str(tmp_path) in os.environ["PATH"].split(os.pathsep)


def test_docker_path_does_not_duplicate_path_entry(monkeypatch, tmp_path):
    fake_docker = tmp_path / "docker.exe"
    fake_docker.touch()
    monkeypatch.setattr("graph.deploy_trigger.shutil.which", lambda name: None)
    monkeypatch.setattr("graph.deploy_trigger.Path", lambda *_: fake_docker)
    monkeypatch.setenv("PATH", str(tmp_path))

    _docker_path()

    assert os.environ["PATH"].split(os.pathsep).count(str(tmp_path)) == 1


def test_acquire_lock_returns_worker_index_when_free():
    worker = _acquire_lock()
    assert worker in range(MAX_CONCURRENT_DEPLOYS)


def test_acquire_lock_returns_none_when_all_slots_held():
    for _ in range(MAX_CONCURRENT_DEPLOYS):
        assert _acquire_lock() is not None

    assert _acquire_lock() is None


def test_acquire_lock_reclaims_stale_lock():
    lock_file = _lock_file(0)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.touch()
    stale_time = time.time() - 100_000
    os.utime(lock_file, (stale_time, stale_time))

    assert _acquire_lock() == 0


def test_deploy_trigger_node_rejects_call_when_all_slots_busy():
    for _ in range(MAX_CONCURRENT_DEPLOYS):
        _acquire_lock()

    fake_run = _make_run({"info": FakeCompleted(returncode=0)})
    result = deploy_trigger_node({"repo": "owner/name"}, gh_client=FakeGithub(), run=fake_run)

    assert f"이미 배포가 {MAX_CONCURRENT_DEPLOYS}건 진행 중입니다" in result["results"]["deploy"]


def test_deploy_trigger_node_allows_deploy_when_a_slot_is_still_free():
    for _ in range(MAX_CONCURRENT_DEPLOYS - 1):
        _acquire_lock()

    fake_run = _make_run(
        {
            "info": FakeCompleted(returncode=0),
            "clone": FakeCompleted(returncode=0),
            "build": FakeCompleted(returncode=0),
            "run": FakeCompleted(returncode=0),
        }
    )

    result = deploy_trigger_node(
        {"repo": "owner/name"}, gh_client=FakeGithub(), run=fake_run, health_check=lambda url: True
    )

    assert "배포 완료" in result["results"]["deploy"]


def test_deploy_trigger_node_releases_lock_after_success():
    fake_run = _make_run(
        {
            "info": FakeCompleted(returncode=0),
            "clone": FakeCompleted(returncode=0),
            "build": FakeCompleted(returncode=0),
            "run": FakeCompleted(returncode=0),
        }
    )

    deploy_trigger_node(
        {"repo": "owner/name"}, gh_client=FakeGithub(), run=fake_run, health_check=lambda url: True
    )

    assert not _lock_file(0).exists()


def test_parse_exposed_port_reads_single_expose():
    assert _parse_exposed_port("FROM node:20\nEXPOSE 3000\nCMD [\"npm\", \"start\"]") == 3000


def test_parse_exposed_port_uses_first_when_multiple():
    assert _parse_exposed_port("EXPOSE 5000\nEXPOSE 9000") == 5000


def test_parse_exposed_port_strips_protocol_suffix():
    assert _parse_exposed_port("EXPOSE 8080/tcp") == 8080


def test_parse_exposed_port_ignores_case():
    assert _parse_exposed_port("expose 4000") == 4000


def test_parse_exposed_port_returns_none_when_missing():
    assert _parse_exposed_port("FROM node:20\nCMD [\"npm\", \"start\"]") is None


def test_parse_exposed_port_returns_none_for_unresolved_arg():
    assert _parse_exposed_port("ARG PORT=3000\nEXPOSE $PORT") is None


def test_resolve_container_port_uses_dockerfile_expose(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM node:20\nEXPOSE 3000\n")

    assert _resolve_container_port(tmp_path) == 3000


def test_resolve_container_port_falls_back_when_no_dockerfile(tmp_path):
    assert _resolve_container_port(tmp_path) == DEFAULT_CONTAINER_PORT


def test_resolve_container_port_falls_back_when_no_expose(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM node:20\nCMD [\"npm\", \"start\"]\n")

    assert _resolve_container_port(tmp_path) == DEFAULT_CONTAINER_PORT


def test_deploy_trigger_node_maps_discovered_container_port(tmp_path, monkeypatch):
    monkeypatch.setattr("graph.deploy_trigger._clone_dir", lambda worker: tmp_path)
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            # 실제 git clone은 clone_dir을 새로 만든다 — _clone_repo가 지운 걸 흉내내서 복구
            tmp_path.mkdir(parents=True, exist_ok=True)
            (tmp_path / "Dockerfile").write_text("FROM node:20\nEXPOSE 3000\n")
        if key == "run":
            captured["cmd"] = cmd
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {"repo": "owner/name"},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    assert any(arg.endswith(":3000") for arg in captured["cmd"])


def test_slot_name_replaces_slash():
    assert _slot_name("owner/name") == "kosa-deploy-owner-name"


def test_slot_name_lowercases():
    assert _slot_name("Owner/Name") == "kosa-deploy-owner-name"


def test_slot_name_differs_per_repo():
    assert _slot_name("owner/repo-a") != _slot_name("owner/repo-b")


def test_slot_name_appends_branch_when_not_default():
    assert _slot_name("owner/repo", "feat/x", "main") == "kosa-deploy-owner-repo-feat-x"


def test_slot_name_omits_branch_when_it_equals_default():
    assert _slot_name("owner/repo", "main", "main") == "kosa-deploy-owner-repo"


def test_slot_name_omits_branch_when_not_provided():
    assert _slot_name("owner/repo") == "kosa-deploy-owner-repo"


def test_deploy_trigger_node_uses_repo_specific_slot():
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            clone_dir = _clone_dir(0)
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "Dockerfile").write_text("FROM scratch\n")
        if key == "build":
            captured["build_tag"] = cmd[cmd.index("-t") + 1]
        if key == "run":
            captured["container_name"] = cmd[cmd.index("--name") + 1]
            captured["run_image"] = cmd[-1]
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {"repo": "owner/repo-a"},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    expected = _slot_name("owner/repo-a")
    assert captured["build_tag"] == expected
    assert captured["container_name"] == expected
    assert captured["run_image"] == expected


def test_deploy_trigger_node_uses_different_slot_for_different_repo():
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            clone_dir = _clone_dir(0)
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "Dockerfile").write_text("FROM scratch\n")
        if key == "build":
            captured["build_tag"] = cmd[cmd.index("-t") + 1]
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {"repo": "owner/repo-b"},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    assert captured["build_tag"] == _slot_name("owner/repo-b")
    assert captured["build_tag"] != _slot_name("owner/repo-a")


def test_deploy_trigger_node_uses_branch_specific_slot_when_branch_mentioned():
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            captured["clone_branch"] = cmd[cmd.index("--branch") + 1]
            clone_dir = _clone_dir(0)
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "Dockerfile").write_text("FROM scratch\n")
        if key == "build":
            captured["build_tag"] = cmd[cmd.index("-t") + 1]
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {"repo": "owner/repo-a", "request": "feat/x 브랜치로 배포해줘", "branches": ["beta", "feat/x"]},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    assert captured["clone_branch"] == "feat/x"
    assert captured["build_tag"] == _slot_name("owner/repo-a", "feat/x", "beta")
    assert captured["build_tag"] != _slot_name("owner/repo-a")  # default-branch slot untouched


def test_deploy_trigger_node_keeps_bare_slot_when_default_branch_mentioned():
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            clone_dir = _clone_dir(0)
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "Dockerfile").write_text("FROM scratch\n")
        if key == "build":
            captured["build_tag"] = cmd[cmd.index("-t") + 1]
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {"repo": "owner/repo-a", "request": "beta 브랜치 배포해줘", "branches": ["beta", "feat/x"]},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    assert captured["build_tag"] == _slot_name("owner/repo-a")


def test_deploy_trigger_node_uses_branch_specific_slot_for_pr_driven_deploy():
    """PR-number-driven deploys land in a branch-suffixed slot too, same as an
    explicitly-named branch — pinning this so it's a deliberate, tested behavior
    rather than a silent side effect of _resolve_ref's PR-branch priority."""
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            captured["clone_branch"] = cmd[cmd.index("--branch") + 1]
            clone_dir = _clone_dir(0)
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / "Dockerfile").write_text("FROM scratch\n")
        if key == "build":
            captured["build_tag"] = cmd[cmd.index("-t") + 1]
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {
            "repo": "owner/repo-a",
            "pr_number": 42,
            "prs": [{"number": 42, "branch": "demo/bug-1"}],
        },
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    assert captured["clone_branch"] == "demo/bug-1"
    assert captured["build_tag"] == _slot_name("owner/repo-a", "demo/bug-1", "beta")


def test_find_compose_file_detects_docker_compose_yml(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}")

    assert _find_compose_file(tmp_path) == tmp_path / "docker-compose.yml"


def test_find_compose_file_detects_compose_yaml_variant(tmp_path):
    (tmp_path / "compose.yaml").write_text("services: {}")

    assert _find_compose_file(tmp_path) == tmp_path / "compose.yaml"


def test_find_compose_file_returns_none_when_absent(tmp_path):
    assert _find_compose_file(tmp_path) is None


def test_find_compose_file_prefers_docker_compose_yml_over_compose_yaml(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}")
    (tmp_path / "compose.yaml").write_text("services: {}")

    assert _find_compose_file(tmp_path) == tmp_path / "docker-compose.yml"


def test_compose_services_running_true_when_all_running(tmp_path):
    compose_file = tmp_path / "docker-compose.yml"

    def fake_run(cmd, **kwargs):
        return FakeCompleted(stdout="web\ndb\n")

    assert _compose_services_running("docker", "slot", compose_file, fake_run) is True


def test_compose_services_running_false_when_some_not_running(tmp_path):
    compose_file = tmp_path / "docker-compose.yml"

    def fake_run(cmd, **kwargs):
        if "--status" in cmd:
            return FakeCompleted(stdout="web\n")
        return FakeCompleted(stdout="web\ndb\n")

    assert _compose_services_running("docker", "slot", compose_file, fake_run) is False


def test_compose_services_running_false_when_no_services_declared(tmp_path):
    compose_file = tmp_path / "docker-compose.yml"

    def fake_run(cmd, **kwargs):
        return FakeCompleted(stdout="")

    assert _compose_services_running("docker", "slot", compose_file, fake_run) is False


def test_deploy_trigger_node_uses_compose_when_compose_file_present(tmp_path, monkeypatch):
    monkeypatch.setattr("graph.deploy_trigger._clone_dir", lambda worker: tmp_path)
    captured = {}

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            tmp_path.mkdir(parents=True, exist_ok=True)
            (tmp_path / "docker-compose.yml").write_text("services:\n  web:\n")
        if "compose" in cmd and "up" in cmd:
            captured["up_cmd"] = cmd
        return FakeCompleted(returncode=0)

    result = deploy_trigger_node(
        {"repo": "owner/repo-a"},
        gh_client=FakeGithub(),
        run=fake_run,
        compose_health_check=lambda *a, **kw: True,
    )

    assert "up_cmd" in captured
    assert "--build" in captured["up_cmd"]
    assert "-p" in captured["up_cmd"]
    assert _slot_name("owner/repo-a") in captured["up_cmd"]
    assert "배포 완료" in result["results"]["deploy"]
    assert "docker compose" in result["results"]["deploy"]


def test_deploy_trigger_node_skips_dockerfile_build_when_compose_present(tmp_path, monkeypatch):
    monkeypatch.setattr("graph.deploy_trigger._clone_dir", lambda worker: tmp_path)

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            tmp_path.mkdir(parents=True, exist_ok=True)
            (tmp_path / "docker-compose.yml").write_text("services:\n  web:\n")
        assert key != "build", "compose 레포는 단일 Dockerfile build를 타면 안 된다"
        return FakeCompleted(returncode=0)

    deploy_trigger_node(
        {"repo": "owner/repo-a"},
        gh_client=FakeGithub(),
        run=fake_run,
        compose_health_check=lambda *a, **kw: True,
    )


def test_deploy_trigger_node_reports_compose_up_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("graph.deploy_trigger._clone_dir", lambda worker: tmp_path)

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            tmp_path.mkdir(parents=True, exist_ok=True)
            (tmp_path / "docker-compose.yml").write_text("services:\n  web:\n")
        if "compose" in cmd and "up" in cmd:
            return FakeCompleted(returncode=1, stderr="ERROR: service 'web' failed to build")
        return FakeCompleted(returncode=0)

    result = deploy_trigger_node({"repo": "owner/repo-a"}, gh_client=FakeGithub(), run=fake_run)

    assert "기동에 실패" in result["results"]["deploy"]
    assert "service 'web' failed to build" in result["results"]["deploy"]


def test_deploy_trigger_node_reports_compose_services_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr("graph.deploy_trigger._clone_dir", lambda worker: tmp_path)

    def fake_run(cmd, **kwargs):
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "clone":
            tmp_path.mkdir(parents=True, exist_ok=True)
            (tmp_path / "docker-compose.yml").write_text("services:\n  web:\n")
        if "logs" in cmd:
            return FakeCompleted(stdout="web exited with code 1")
        return FakeCompleted(returncode=0)

    result = deploy_trigger_node(
        {"repo": "owner/repo-a"},
        gh_client=FakeGithub(),
        run=fake_run,
        compose_health_check=lambda *a, **kw: False,
    )

    assert "running 상태가 아닙니다" in result["results"]["deploy"]
    assert "web exited with code 1" in result["results"]["deploy"]


def test_deploy_trigger_node_reports_success():
    fake_run = _make_run(
        {
            "info": FakeCompleted(returncode=0),
            "clone": FakeCompleted(returncode=0),
            "build": FakeCompleted(returncode=0),
            "run": FakeCompleted(returncode=0),
        }
    )

    result = deploy_trigger_node(
        {"repo": "owner/name"},
        gh_client=FakeGithub(),
        run=fake_run,
        health_check=lambda url: True,
    )

    assert "배포 완료" in result["results"]["deploy"]
    assert "beta" in result["results"]["deploy"]


def test_deploy_trigger_node_reports_missing_dockerfile(tmp_path, monkeypatch):
    monkeypatch.setattr("graph.deploy_trigger._clone_dir", lambda worker: tmp_path)

    def fake_run(cmd, **kwargs):
        return FakeCompleted(returncode=0)

    result = deploy_trigger_node({"repo": "owner/name"}, gh_client=FakeGithub(), run=fake_run)

    assert result["results"]["deploy"] == DEPLOY_ERROR_DOCKERFILE_NOT_EXIST


def test_deploy_trigger_node_does_not_attempt_build_when_dockerfile_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("graph.deploy_trigger._clone_dir", lambda worker: tmp_path)
    build_called = False

    def fake_run(cmd, **kwargs):
        nonlocal build_called
        key = cmd[1] if len(cmd) > 1 else cmd[0]
        if key == "build":
            build_called = True
        return FakeCompleted(returncode=0)

    deploy_trigger_node({"repo": "owner/name"}, gh_client=FakeGithub(), run=fake_run)

    assert build_called is False
