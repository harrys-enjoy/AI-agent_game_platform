"""로컬 개발용 실행기 — a2a_server.py가 스스로를 127.0.0.1로 광고하게 한다.

기본값(DEV_AGENT_PUBLIC_URL 미설정 시 "http://dev-agent:8003")은 docker-compose 네트워크
전용이라, main_agent를 로컬에서 직접 붙일 때는 이 스크립트로 띄워야 한다.

main_agent는 workspace_id를 안 보내는데(실측), 실제 환경 파일에 DEFAULT_WORKSPACE_ID가
없으면 모든 요청이 "레포를 결정할 수 없습니다" 400으로 막힌다. 이 프로젝트 레포로
setdefault — 실제 환경 파일에 이미 값이 있으면 이건 무시된다.
"""
import atexit
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("DEV_AGENT_PUBLIC_URL", "http://127.0.0.1:8003")
os.environ.setdefault("DEFAULT_WORKSPACE_ID", "game-team-a")
os.environ.setdefault("WORKSPACE_REPO_MAP", "game-team-a=harrys-enjoy/AI-agent_game_platform")

_KOSA_FRONT_DIR = Path(__file__).resolve().parent / "kosa_front"


def _start_kosa_front() -> subprocess.Popen:
    """kosa_front(main_agent 화면에 iframe으로 들어가는 대시보드)를 같이 띄운다."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=_KOSA_FRONT_DIR,
    )
    atexit.register(proc.terminate)
    return proc


if __name__ == "__main__":
    import uvicorn

    _start_kosa_front()
    uvicorn.run("a2a_server:app", host="127.0.0.1", port=8003)
