import os
import re
from typing import Literal

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .contracts import AgentCard, TaskEvent
from .conversation_store import ConversationStore
from .a2a_client import A2AClient
from .main_agent_prompt import get_agent_system_prompt
from .orchestrator import Orchestrator
from .registry import AgentRegistry
from .task_store import TaskStore


app = FastAPI(title="Main AI Orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type", "authorization"],
)
store = TaskStore("main_agent.db")
conversation_store = ConversationStore("main_agent.db")
registry = AgentRegistry(timeout=0.25)


class TaskRequest(BaseModel):
    request: str


class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    session_id: str | None = None


class ChatReplyRequest(BaseModel):
    content: str


class StoryCreateRequest(BaseModel):
    name: str
    keywords: list[str]
    answer: str


class LocalClient:
    async def send_message(self, agent_url: str, request: dict) -> dict:
        return {"agent": agent_url, "summary": request["message"], "status": "succeeded"}


cards = [
    AgentCard(name="workmate-agent", description="업무지원 Agent", url=os.getenv("WORKMATE_AGENT_URL", "http://workmate-agent:8001/a2a"), skills=[{"id": "daily_briefing", "name": "일일 브리핑"}]),
    AgentCard(name="video-agent", description="영상 생성 Agent", url=os.getenv("VIDEO_AGENT_URL", "http://video-agent:8002/a2a"), skills=[{"id": "video_draft", "name": "영상 초안"}]),
    AgentCard(name="dev-agent", description="개발 보조 Agent", url=os.getenv("DEV_AGENT_URL", "http://dev-agent:8003/a2a"), skills=[{"id": "code_review", "name": "코드 리뷰"}]),
    AgentCard(name="game-qna-agent", description="게임 Q&A Agent", url=os.getenv("GAME_QNA_AGENT_URL", os.getenv("GAME_QA_AGENT_URL", "http://game-qa-agent:3000/message:send")), skills=[{"id": "game_qa", "name": "게임 Q&A"}]),
]
CHAT_AGENT_NAMES = {
    "Workmate AI": "workmate-agent",
    "Video Generation": "video-agent",
    "Development Assistant": "dev-agent",
    "Game Q&A": "game-qna-agent",
}

GAME_QNA_COMMANDS = {
    "/planning": {
        "mode": "dev-guide",
        "template": "게임 기획안을 작성해줘. 목표, 핵심 규칙, 진행 단계, 고려할 위험을 정리해줘.",
    },
    "/art": {
        "mode": "dev-guide",
        "template": "Video Generation용 참고 프롬프트를 작성해줘. 주제, 행동, 환경, 스타일, 카메라, 조명과 분위기를 정리해줘.",
    },
    "/lore": {
        "mode": "lore",
        "template": "이 게임 세계관의 인물, 세력, 사건 관계를 정리해줘.",
    },
    "/catalog": {
        "mode": "catalog",
        "template": "게임 카탈로그에서 관련 콘텐츠를 찾아줘.",
    },
    "/codexbook": {
        "mode": "codex",
        "template": "도감에서 관련 캐릭터, 몬스터, 아이템을 찾아줘.",
    },
}


GAME_QNA_SOURCE_LABELS = {
    "dev-guide": "Source: Guide (planning / art)",
    "lore": "Source: World Lore",
    "catalog": "Source: Catalog (game content)",
    "codex": "Source: Codex (characters / monsters / items)",
}


def parse_game_qna_command(content: str) -> dict:
    text = content.strip()
    if re.fullmatch(r"/(?:\?|help)", text, re.IGNORECASE):
        return {"kind": "help", "commands": list(GAME_QNA_COMMANDS)}
    match = re.fullmatch(r"/(planning|art|lore|catalog|codexbook)(?:\s+(.*))?", text, re.IGNORECASE)
    if not match:
        return {"kind": "request", "mode": "lore", "content": text, "command": None}
    command = f"/{match.group(1).lower()}"
    config = GAME_QNA_COMMANDS[command]
    return {
        "kind": "request",
        "mode": config["mode"],
        "content": (match.group(2) or "").strip() or config["template"],
        "command": command,
    }


def resolve_chat_agent(agent_name: str, content: str) -> str:
    if agent_name == "Workmate AI" and re.search(r"홍길동|전우치|세계관|스토리|lore|game|게임", content, re.IGNORECASE):
        return "game-qna-agent"
    return CHAT_AGENT_NAMES.get(agent_name, agent_name)


def build_agent_request(agent_name: str, message: str, mode: str | None = None) -> dict:
    request = {
        "message": message,
        "locale": "ko",
        "system_prompt": get_agent_system_prompt(agent_name),
    }
    if mode is not None:
        request["mode"] = mode
    return request


for card in cards:
    base_url = card.url.rsplit("/message:send", 1)[0].removesuffix("/a2a")
    registry.register(card.name, base_url)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/agents")
def list_agents() -> list[AgentCard]:
    return cards


@app.get("/api/chats/{agent_name}/messages")
def list_chat_messages(agent_name: str, session_id: str | None = None) -> list[dict[str, str]]:
    return conversation_store.list_messages(agent_name, session_id)


@app.get("/api/chats/{agent_name}/session")
def get_chat_session(agent_name: str) -> dict:
    session_id = conversation_store.current_session(agent_name)
    return {"session_id": session_id, "messages": conversation_store.list_messages(agent_name, session_id)}


@app.post("/api/chats/{agent_name}/reset")
def reset_chat_session(agent_name: str) -> dict[str, str]:
    return {"session_id": conversation_store.reset(agent_name)}


@app.post("/api/chats/{agent_name}/messages", status_code=201)
def save_chat_message(agent_name: str, payload: ChatMessageRequest) -> dict[str, str]:
    return conversation_store.append(agent_name, payload.role, payload.content, payload.session_id)


@app.post("/api/chats/{agent_name}/reply")
async def chat_reply(agent_name: str, payload: ChatReplyRequest) -> dict:
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Message is required")
    card_name = resolve_chat_agent(agent_name, payload.content)
    configured_card = next((card for card in cards if card.name == card_name), None)
    if configured_card is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    live_cards = await registry.refresh() if os.getenv("LIVE_AGENT_DISCOVERY", "false").lower() == "true" else {}
    card = live_cards.get(card_name, configured_card)
    client = A2AClient() if live_cards else LocalClient()
    command = parse_game_qna_command(payload.content) if card_name == "game-qna-agent" else None
    if command and command["kind"] == "help":
        return {"answer": "사용 가능한 Game Q&A 명령어: " + ", ".join(command["commands"]), "agent": card_name, "status": "succeeded"}
    request = build_agent_request(card_name, command["content"] if command else payload.content)
    if card_name == "game-qna-agent":
        request["mode"] = command["mode"] if command else "lore"
    try:
        result = await client.send_message(card.url, request)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    answer = result.get("answer") or result.get("summary") or "응답을 받지 못했습니다."
    effective_mode = result.get("mode") or request.get("mode")
    if card_name == "game-qna-agent" and not answer.startswith("[Source:"):
        source_label = GAME_QNA_SOURCE_LABELS.get(effective_mode, "Source: Game Q&A")
        answer = f"[{source_label}]\n{answer}"
    return {
        "answer": answer,
        "agent": card_name,
        "mode": effective_mode,
        "command": command.get("command") if command and command["kind"] == "request" else None,
        "status": result.get("status", "succeeded"),
    }


@app.post("/api/stories", status_code=201)
async def create_story(payload: StoryCreateRequest) -> dict:
    catalog_url = os.getenv("GAME_QNA_AGENT_URL", os.getenv("GAME_QA_AGENT_URL", "http://game-qa-agent:3000/message:send"))
    base_url = catalog_url.rsplit("/message:send", 1)[0].removesuffix("/a2a")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{base_url}/knowledge/lore", json=payload.model_dump())
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Catalog story API unavailable: {exc}") from exc


@app.post("/api/tasks", status_code=202)
async def create_task(payload: TaskRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    live_cards = await registry.refresh() if os.getenv("LIVE_AGENT_DISCOVERY", "false").lower() == "true" else {}
    active_cards = list(live_cards.values()) or cards
    client = A2AClient() if live_cards else LocalClient()
    orchestrator = Orchestrator(client, store)
    selected = orchestrator._select(payload.request, active_cards)
    task = store.create(payload.request, [card.name for card in selected])

    async def run_existing() -> None:
        store.update(task.task_id, status="running")
        results = []
        try:
            for card in selected:
                request = build_agent_request(
                    card.name,
                    payload.request,
                    "lore" if card.name == "game-qna-agent" else None,
                )
                results.append(await orchestrator.client.send_message(card.url, request))
            store.update(task.task_id, status="succeeded", result={"results": results})
        except Exception as exc:
            store.update(task.task_id, status="failed", result={"results": results}, error=str(exc))

    background_tasks.add_task(run_existing)
    return {"task_id": task.task_id, "status": task.status}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/tasks/{task_id}/events")
def get_task_events(task_id: str):
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.events


@app.post("/api/tasks/{task_id}/retry", status_code=202)
async def retry_task(task_id: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    selected = [card for card in cards if card.name in task.selected_agents]
    store.append_event(task_id, TaskEvent(type="retry", message="작업 재시도"))
    store.update(task_id, status="running", error=None)

    async def rerun() -> None:
        results = []
        for card in selected:
            results.append(await LocalClient().send_message(card.url, build_agent_request(card.name, task.request)))
        store.update(task_id, status="succeeded", result={"results": results})

    background_tasks.add_task(rerun)
    return {"task_id": task_id, "status": "running"}
