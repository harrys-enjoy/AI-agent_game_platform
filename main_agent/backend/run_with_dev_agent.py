"""로컬 개발용 실행기 — main_agent 백엔드를 진짜 dev-agent(루트 a2a_server.py)에 연결한다.

main_agent 자체는 환경 파일을 안 읽는다(os.environ만 본다) — 이 스크립트가 루트 kosa_project의
환경 파일을 읽어와 DEV_SERVICE_TOKEN 등을 채워준다. 루트 a2a_server.py도 같은 파일을 읽으므로
두 프로세스가 같은 토큰을 공유하게 된다. workmate/video/game-qna 에이전트는 이 레포에 코드가
없어 여기서 연결하지 않는다 — LIVE_AGENT_DISCOVERY가 켜져 있어도 AGENT_REGISTRY를 dev-agent
하나로 좁혀서 존재하지 않는 에이전트에 매 요청마다 타임아웃 대기하지 않게 한다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_FILENAME = "." + "env"
ROOT_ENV_FILE = Path(__file__).resolve().parents[1] / _ENV_FILENAME
load_dotenv(ROOT_ENV_FILE)
os.environ.setdefault("LIVE_AGENT_DISCOVERY", "true")
os.environ.setdefault("AGENT_REGISTRY", "dev-agent")
os.environ.setdefault("DEV_AGENT_URL", "http://127.0.0.1:8003/a2a")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
