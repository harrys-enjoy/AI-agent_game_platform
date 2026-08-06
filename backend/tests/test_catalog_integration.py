import os
import subprocess
import time

import httpx
import pytest

from app.a2a_client import A2AClient


CATALOG_DIR = r"C:\Users\희정\Downloads\Nvidia project\Catalog & Manual(Game project)"


@pytest.mark.asyncio
async def test_catalog_real_node_server_responds_to_a2a_client():
    process = subprocess.Popen(
        ["node", "src/server.js"],
        cwd=CATALOG_DIR,
        env={**os.environ, "PORT": "3010"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        async with httpx.AsyncClient() as http:
            for _ in range(30):
                try:
                    response = await http.get("http://127.0.0.1:3010/health")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await __import__("asyncio").sleep(0.2)
            else:
                pytest.fail("Catalog Node server did not become healthy")

        client = A2AClient(timeout=3)
        result = await client.send_message(
            "http://127.0.0.1:3010/message:send",
            {"message": "전우치와 홍길동의 신념 대립을 설명해줘", "mode": "lore", "locale": "ko"},
        )

        assert result["status"] == "succeeded"
        assert result["answer"]
    finally:
        process.terminate()
        process.wait(timeout=5)
