"""대상 레포의 지정 브랜치/PR을 이 PC의 Docker Desktop에 직접 배포한다.

GitHub Actions를 거치지 않는다 — deploy.yml 등 기존 워크플로가 upstream 전용으로
하드 게이트돼 있고 포크는 부모 레포의 secrets를 상속받지 않기 때문이다. 대신
git clone -> docker build -> 기존 배포 컨테이너 교체 -> 헬스체크까지 전부
subprocess로 직접 수행하는 결정적 코드다. LLM 호출 없음.

레포 루트에 docker-compose.yml(또는 compose.yaml 등)이 있으면 단일 Dockerfile
빌드 대신 `docker compose up -d --build`로 전체 스택을 올린다.
"""

import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from github import Github

from graph.ci_trigger import _resolve_ref
from graph.fetch import get_github_client

_SLOT_PREFIX = "kosa-deploy"
_UNSAFE_SLOT_CHARS = re.compile(r"[^a-z0-9_.-]")
DEPLOY_BASE_DIR = Path(tempfile.gettempdir()) / "kosa_deploy"
MAX_CONCURRENT_DEPLOYS = 3
PORT_RANGE = range(8000, 8011)
DEFAULT_CONTAINER_PORT = 8000  # Dockerfile에 EXPOSE가 없을 때만 쓰는 대체값
_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(\d+)", re.IGNORECASE | re.MULTILINE)
COMPOSE_FILE_CANDIDATES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
HEALTH_TIMEOUT_SEC = 30
HEALTH_INTERVAL_SEC = 2
CLONE_TIMEOUT_SEC = 300
BUILD_TIMEOUT_SEC = 900
QUICK_TIMEOUT_SEC = 30
LOCK_MAX_AGE_SEC = CLONE_TIMEOUT_SEC + BUILD_TIMEOUT_SEC + HEALTH_TIMEOUT_SEC + 60
DEPLOY_ERROR_DOCKERFILE_NOT_EXIST = "dockerfile_not_exist"


def _clone_dir(worker: int) -> Path:
    """워커 슬롯 전용 clone/build 작업 디렉터리.

    슬롯별로 분리해야 동시 배포 두 건이 같은 경로에 clone하며 서로의 체크아웃을
    덮어쓰는 레이스를 피한다.
    """
    return DEPLOY_BASE_DIR / f"current-{worker}"


def _lock_file(worker: int) -> Path:
    return DEPLOY_BASE_DIR / f"deploy-{worker}.lock"


def _acquire_lock() -> int | None:
    """MAX_CONCURRENT_DEPLOYS개의 워커 슬롯 중 비어있는 하나를 잡고 그 번호를 반환한다.

    슬롯마다 clone 디렉터리가 분리돼 있어(`_clone_dir`) 동시에 여러 배포가 진행돼도
    서로의 체크아웃/빌드를 덮어쓰지 않는다. 슬롯이 다 차 있으면 기다리지 않고 즉시
    None을 반환한다. 프로세스가 강제 종료돼 락이 남아도, 배포가 걸릴 수 있는 최대
    시간보다 오래된 락은 죽은 락으로 보고 정리한다 — 소규모 프로젝트라 영구 락스텝보다
    가끔의 경합 쪽이 더 싸다.
    ponytail: 같은 레포를 서로 다른 워커 슬롯이 동시에 배포하면 컨테이너 이름(`_slot_name`)이
    겹쳐 레이스가 날 수 있다 — 레포당 동시 배포 1건 제한이 필요해지면 레포별 락을 추가할 것.
    """
    DEPLOY_BASE_DIR.mkdir(parents=True, exist_ok=True)
    for worker in range(MAX_CONCURRENT_DEPLOYS):
        lock_file = _lock_file(worker)
        if lock_file.exists():
            age_sec = time.time() - lock_file.stat().st_mtime
            if age_sec > LOCK_MAX_AGE_SEC:
                lock_file.unlink(missing_ok=True)
            else:
                continue
        try:
            lock_file.touch(exist_ok=False)
            return worker
        except FileExistsError:
            continue
    return None


def _release_lock(worker: int) -> None:
    _lock_file(worker).unlink(missing_ok=True)


def _docker_path() -> str:
    """docker CLI 경로를 찾는다. PATH에 없으면 Docker Desktop의 알려진 설치 경로를 시도한다.

    폴백을 쓸 때는 그 디렉터리를 PATH에도 추가한다 — docker CLI가 이미지를 pull할 때
    자격증명 조회를 위해 같은 폴더의 docker-credential-desktop을 PATH로 찾아 실행하는데,
    PATH에 없으면 공개 이미지 빌드조차 "credential helper not found"로 실패한다.
    """
    found = shutil.which("docker")
    if found:
        return found
    fallback = Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
    if fallback.exists():
        fallback_dir = str(fallback.parent)
        path = os.environ.get("PATH", "")
        if fallback_dir not in path.split(os.pathsep):
            os.environ["PATH"] = fallback_dir + os.pathsep + path
        return str(fallback)
    return "docker"


def _tail(text: str, n: int) -> str:
    """문자열의 마지막 n줄만 남긴다. 로그/에러 출력을 짧게 자를 때 쓴다."""
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


def _slot_name(repo: str, branch: str | None = None, default_branch: str | None = None) -> str:
    """레포별로(그리고 기본 브랜치가 아닌 브랜치를 지정했다면 브랜치별로도) 겹치지 않는
    컨테이너/이미지 이름을 만든다.

    "owner/name" 형태의 "/"는 Docker 이름에 못 쓰므로 치환하고, 이미지 태그는
    소문자만 허용되므로 소문자로 통일한다. 기본 브랜치 배포는 지금까지처럼 브랜치를
    슬롯 이름에 안 붙인다 — 그래야 기존에 떠 있는 배포/삭제 기능과 호환된다. 다른
    브랜치를 명시했을 때만 같은 레포를 나란히 배포할 수 있도록 슬롯을 분리한다.
    """
    safe_repo = _UNSAFE_SLOT_CHARS.sub("-", repo.lower())
    if branch and branch != default_branch:
        safe_branch = _UNSAFE_SLOT_CHARS.sub("-", branch.lower())
        return f"{_SLOT_PREFIX}-{safe_repo}-{safe_branch}"
    return f"{_SLOT_PREFIX}-{safe_repo}"


def _find_free_port(port_range: range = PORT_RANGE) -> int | None:
    """port_range 안에서 로컬 소켓 바인드가 되는 첫 포트를 찾는다. 없으면 None."""
    for port in port_range:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return None


def _parse_exposed_port(dockerfile_text: str) -> int | None:
    """Dockerfile에서 첫 EXPOSE 포트를 읽는다. 여러 개면 첫 줄, 없거나 `EXPOSE $PORT`처럼
    빌드 인자에 의존하면 None."""
    match = _EXPOSE_RE.search(dockerfile_text)
    return int(match.group(1)) if match else None


def _resolve_container_port(clone_dir: Path) -> int:
    """레포의 Dockerfile EXPOSE로 컨테이너 내부 포트를 정한다. Dockerfile이 없거나
    EXPOSE가 없으면 DEFAULT_CONTAINER_PORT로 되돌아간다."""
    try:
        text = (clone_dir / "Dockerfile").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return DEFAULT_CONTAINER_PORT
    return _parse_exposed_port(text) or DEFAULT_CONTAINER_PORT


def _find_compose_file(clone_dir: Path) -> Path | None:
    """레포 루트에서 compose 파일을 찾는다. docker compose CLI가 쓰는 것과 같은 우선순위."""
    for name in COMPOSE_FILE_CANDIDATES:
        candidate = clone_dir / name
        if candidate.exists():
            return candidate
    return None


def _compose_services_running(docker: str, slot: str, compose_file: Path, run) -> bool:
    """compose 프로젝트에 정의된 서비스 전부가 running 상태인지 본다.

    compose 스택은 서비스가 여러 개고 포트도 파일이 직접 정하므로, 단일 컨테이너
    경로처럼 HTTP로 특정 URL을 찔러볼 수 없다 — `docker compose ps`의 상태로 판단한다.
    """
    total = run(
        # -a: a crashed/exited container otherwise drops out of the default `ps` listing
        # too, so a service that immediately died would silently vanish from both sides
        # of this comparison and the crash would read as "all services running".
        [docker, "compose", "-p", slot, "-f", str(compose_file), "ps", "--services", "-a"],
        capture_output=True,
        text=True,
        timeout=QUICK_TIMEOUT_SEC,
    )
    running = run(
        [docker, "compose", "-p", slot, "-f", str(compose_file), "ps", "--services", "--status", "running"],
        capture_output=True,
        text=True,
        timeout=QUICK_TIMEOUT_SEC,
    )
    total_services = {line for line in total.stdout.splitlines() if line.strip()}
    running_services = {line for line in running.stdout.splitlines() if line.strip()}
    return bool(total_services) and total_services == running_services


def _wait_for_compose_healthy(
    docker: str,
    slot: str,
    compose_file: Path,
    run,
    timeout_sec: int = HEALTH_TIMEOUT_SEC,
    interval_sec: int = HEALTH_INTERVAL_SEC,
) -> bool:
    """모든 서비스가 running이 될 때까지 폴링한다."""
    deadline = time.monotonic() + timeout_sec
    while True:
        if _compose_services_running(docker, slot, compose_file, run):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_sec)


def _deploy_compose(docker: str, slot: str, compose_file: Path, run, compose_health_check) -> dict:
    """compose 파일이 있는 레포는 단일 Dockerfile 빌드 대신 스택 전체를 올린다.

    호스트 포트는 compose 파일이 직접 정의하므로 PORT_RANGE에서 빈 포트를 찾아
    매핑하지 않는다 — 실제 접속 URL은 사용자가 compose 파일이나 `docker compose ps`로 확인해야 한다.
    """
    try:
        up_result = run(
            [docker, "compose", "-p", slot, "-f", str(compose_file), "up", "-d", "--build"],
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return {"results": {"deploy": "compose 빌드/기동이 시간 제한을 넘겨 중단했습니다."}}

    if up_result.returncode != 0:
        tail = _tail(up_result.stderr or up_result.stdout or "", 20)
        return {"results": {"deploy": f"docker compose 기동에 실패했습니다.\n\n{tail}"}}

    if not compose_health_check(docker, slot, compose_file, run):
        logs = run(
            [docker, "compose", "-p", slot, "-f", str(compose_file), "logs", "--tail", "20"],
            capture_output=True,
            text=True,
            timeout=QUICK_TIMEOUT_SEC,
        )
        tail = _tail(logs.stdout or logs.stderr or "", 20)
        return {"results": {"deploy": f"compose 서비스가 모두 running 상태가 아닙니다.\n\n{tail}"}}

    return {
        "results": {
            "deploy": (
                f"배포 완료 (docker compose, 프로젝트 {slot}). "
                f"포트는 {compose_file.name}의 ports: 정의를 따릅니다 — "
                f"`docker compose -p {slot} ps`로 확인하세요."
            )
        }
    }


def _wait_for_health(
    url: str, timeout_sec: int = HEALTH_TIMEOUT_SEC, interval_sec: int = HEALTH_INTERVAL_SEC
) -> bool:
    """url이 응답할 때까지 폴링한다. 5xx는 실패로 친다."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=interval_sec) as resp:
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(interval_sec)
    return False


def _force_remove_readonly(func, path, exc_info) -> None:
    """git이 만드는 읽기 전용 오브젝트 파일을 Windows에서 rmtree가 못 지우는 문제를 우회한다."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _clone_repo(repo_name: str, ref: str, run, clone_dir: Path) -> str | None:
    """clone_dir을 비우고 얕은 clone을 수행한다. 실패 시 사용자에게 보여줄 메시지, 성공 시 None.

    서브모듈도 함께 받는다 — locales 같은 서브모듈을 쓰는 레포는 이게 없으면 앱이
    실행 중 빈 디렉터리를 만나 그 자리에서 죽는다.
    """
    if clone_dir.exists():
        shutil.rmtree(clone_dir, onerror=_force_remove_readonly)
    clone_dir.parent.mkdir(parents=True, exist_ok=True)

    url = f"https://github.com/{repo_name}.git"
    try:
        result = run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                ref,
                "--recurse-submodules",
                "--shallow-submodules",
                url,
                str(clone_dir),
            ],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return f"{ref} 브랜치를 내려받는 데 시간이 너무 오래 걸려 중단했습니다."
    except OSError as exc:
        return f"{ref} 브랜치를 내려받는 중 오류가 발생했습니다: {exc}"

    if result.returncode != 0:
        return f"{ref} 브랜치를 내려받지 못했습니다.\n\n{(result.stderr or '').strip()}"
    return None


def deploy_trigger_node(
    state: dict,
    gh_client: Github | None = None,
    run=subprocess.run,
    health_check=_wait_for_health,
    compose_health_check=_wait_for_compose_healthy,
    port_range: range = PORT_RANGE,
) -> dict:
    docker = _docker_path()

    try:
        info = run([docker, "info"], capture_output=True, text=True, timeout=QUICK_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired):
        return {"results": {"deploy": "Docker Desktop이 실행 중이 아닙니다. 켜고 다시 시도해주세요."}}

    if info.returncode != 0:
        return {"results": {"deploy": "Docker Desktop이 실행 중이 아닙니다. 켜고 다시 시도해주세요."}}

    worker = _acquire_lock()
    if worker is None:
        return {
            "results": {
                "deploy": f"이미 배포가 {MAX_CONCURRENT_DEPLOYS}건 진행 중입니다. 잠시 후 다시 시도해주세요."
            }
        }

    clone_dir = _clone_dir(worker)

    try:
        gh = gh_client or get_github_client()
        repo = gh.get_repo(state["repo"])
        ref = _resolve_ref(state, repo)
        slot = _slot_name(state["repo"], ref, repo.default_branch)

        clone_error = _clone_repo(state["repo"], ref, run, clone_dir)
        if clone_error is not None:
            return {"results": {"deploy": clone_error}}

        compose_file = _find_compose_file(clone_dir)
        if compose_file is not None:
            return _deploy_compose(docker, slot, compose_file, run, compose_health_check)

        if not (clone_dir / "Dockerfile").exists():
            return {"results": {"deploy": DEPLOY_ERROR_DOCKERFILE_NOT_EXIST}}

        try:
            build_result = run(
                [docker, "build", "-t", slot, str(clone_dir)],
                capture_output=True,
                text=True,
                timeout=BUILD_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            return {"results": {"deploy": "이미지 빌드가 시간 제한을 넘겨 중단했습니다."}}

        if build_result.returncode != 0:
            tail = _tail(build_result.stderr or build_result.stdout or "", 20)
            return {"results": {"deploy": f"이미지 빌드에 실패했습니다.\n\n{tail}"}}

        run([docker, "image", "prune", "-f"], capture_output=True, text=True, timeout=QUICK_TIMEOUT_SEC)

        try:
            run([docker, "stop", slot], capture_output=True, text=True, timeout=QUICK_TIMEOUT_SEC)
            run([docker, "rm", slot], capture_output=True, text=True, timeout=QUICK_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass  # 이전 컨테이너 정리 실패는 치명적이지 않다 — 다음 docker run이 이름 충돌로 실패하면
            # 그 시점에 "컨테이너가 시작되지 않았습니다" 메시지로 사용자에게 보고된다

        port = _find_free_port(port_range)
        if port is None:
            lo, hi = port_range.start, port_range.stop - 1
            return {"results": {"deploy": f"사용 가능한 포트를 찾지 못했습니다 ({lo}~{hi})."}}

        container_port = _resolve_container_port(clone_dir)
        run_result = run(
            [docker, "run", "-d", "--name", slot, "-p", f"{port}:{container_port}", slot],
            capture_output=True,
            text=True,
            timeout=QUICK_TIMEOUT_SEC,
        )
        if run_result.returncode != 0:
            stderr = (run_result.stderr or "").strip()
            return {"results": {"deploy": f"컨테이너가 시작되지 않았습니다.\n\n{stderr}"}}

        url = f"http://localhost:{port}/"
        if not health_check(url):
            logs = run(
                [docker, "logs", slot], capture_output=True, text=True, timeout=QUICK_TIMEOUT_SEC
            )
            tail = _tail(logs.stdout or logs.stderr or "", 20)
            return {"results": {"deploy": f"컨테이너는 떠 있지만 응답이 없습니다.\n\n{tail}"}}

        return {"results": {"deploy": f"배포 완료: {url} (브랜치 {ref})"}}
    finally:
        _release_lock(worker)
