import asyncio
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest


CATALOG_DIR = str(Path(__file__).resolve().parents[3] / "qna_agent")
BACKEND_DIR = str(Path(__file__).resolve().parents[1])


async def wait_for(url: str, timeout: float = 8) -> None:
    async with httpx.AsyncClient() as client:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            try:
                if (await client.get(url)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise AssertionError(f"service did not become healthy: {url}")


@pytest.mark.asyncio
async def test_frontend_request_reaches_catalog_through_main_api():
    catalog = subprocess.Popen(
        ["node", "src/server.js"],
        cwd=CATALOG_DIR,
        # 개발자 로컬 qna_agent/.env에 진짜 API_KEY가 있어도 이 테스트는 인증 없는
        # 상태를 가정한다 — 빈 문자열로 덮어써서 로컬 시크릿이 새어 들어오지 않게 한다.
        env={
            **os.environ,
            "PORT": "3010",
            "AGENT_PUBLIC_URL": "http://127.0.0.1:3010",
            "API_KEY": "",
            "GAME_QNA_SERVICE_TOKEN": "",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    main = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010"],
        cwd=BACKEND_DIR,
        env={
            **os.environ,
            "LIVE_AGENT_DISCOVERY": "true",
            "GAME_QA_AGENT_URL": "http://127.0.0.1:3010/message:send",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await wait_for("http://127.0.0.1:3010/health")
        await wait_for("http://127.0.0.1:8010/health")
        async with httpx.AsyncClient(timeout=10) as client:
            created = await client.post(
                "http://127.0.0.1:8010/api/tasks",
                json={"request": "전우치"},
            )
            assert created.status_code == 202
            task_id = created.json()["task_id"]
            for _ in range(150):
                task = await client.get(f"http://127.0.0.1:8010/api/tasks/{task_id}")
                if task.json()["status"] in {"succeeded", "failed"}:
                    break
                await asyncio.sleep(0.2)
            assert task.json()["status"] == "succeeded", task.json()
            assert task.json()["result"]["results"][0]["answer"]
    finally:
        main.terminate()
        catalog.terminate()
        main.wait(timeout=5)
        catalog.wait(timeout=5)
