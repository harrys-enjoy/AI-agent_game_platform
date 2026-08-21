import asyncio
import os
import subprocess

import httpx
import pytest


CATALOG_DIR = r"C:\Users\희정\Downloads\Nvidia project\Catalog & Manual(Game project)"
BACKEND_DIR = r"C:\Users\희정\Downloads\Nvidia project\Main Agent(docker)\main_agent\backend"


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
        env={**os.environ, "PORT": "3010", "AGENT_PUBLIC_URL": "http://127.0.0.1:3010"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    main = subprocess.Popen(
        ["C:\\Anaconda3\\python.exe", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010"],
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
            for _ in range(20):
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
