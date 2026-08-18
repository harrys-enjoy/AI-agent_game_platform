import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app.a2a_client import A2AClient


CATALOG_DIR = str(Path(__file__).resolve().parents[3] / "qna_agent")


@pytest.mark.asyncio
async def test_catalog_real_node_server_responds_to_a2a_client():
    process = subprocess.Popen(
        ["node", "src/server.js"],
        cwd=CATALOG_DIR,
        # 개발자 로컬 qna_agent/.env에 진짜 API_KEY가 있어도 이 테스트는 인증 없는
        # 상태를 가정한다 — 빈 문자열로 덮어써서 로컬 시크릿이 새어 들어오지 않게 한다.
        env={**os.environ, "PORT": "3010", "API_KEY": "", "GAME_QNA_SERVICE_TOKEN": ""},
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

        client = A2AClient(timeout=30)
        result = await client.send_message(
            "http://127.0.0.1:3010/message:send",
            {"message": "전우치와 홍길동의 신념 대립을 설명해줘", "mode": "lore", "locale": "ko"},
        )

        assert result["status"] == "succeeded"
        assert result["answer"]
    finally:
        process.terminate()
        process.wait(timeout=5)
