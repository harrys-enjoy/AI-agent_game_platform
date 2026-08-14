import json
import os
from pathlib import Path

from fastapi import FastAPI

app = FastAPI()
name = os.getenv("AGENT_NAME", "mock-agent")
port = os.getenv("AGENT_PORT", "8001")
card_file = os.getenv("CARD_FILE", "")


@app.get("/health")
def health():
    return {"status": "ok", "agent": name}


@app.get("/.well-known/agent-card.json")
def card():
    if card_file and Path(card_file).exists():
        return json.loads(Path(card_file).read_text(encoding="utf-8"))
    return {"name": name, "description": name, "url": f"http://{name}:{port}/a2a", "skills": []}


@app.post("/a2a")
def a2a(payload: dict):
    message = payload.get("params", {}).get("message", "")
    return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"status": "succeeded", "agent": name, "summary": f"{name} 처리 결과: {message}"}}


@app.post("/a2a/message:send")
def a2a_http_json(payload: dict):
    parts = payload.get("message", {}).get("parts", [])
    message = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))
    return {"message": {"parts": [{"text": f"{name} 처리 결과: {message}"}]}}
