import json
import os
import re
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .contracts import AgentCard, TaskEvent
from .conversation_store import ConversationStore
from .a2a_client import A2AClient
from .errors import A2AError
from .main_agent_prompt import get_agent_system_prompt
from .orchestrator import Orchestrator
from .registry import AgentRegistry
from .router import RouterLLM
from .task_store import TaskStore
from .task_log_store import TaskLogStore
from . import video_agent_client


app = FastAPI(title="Main AI Orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type", "authorization"],
)
store = TaskStore("main_agent.db")
task_log_store = TaskLogStore("main_agent.db")
conversation_store = ConversationStore("main_agent.db")
registry: AgentRegistry
router = RouterLLM()

# video-agent's real pipeline can take several minutes per render (observed ~373s
# for a 16s clip) - the default poll_timeout=30.0 was tuned for the fast mock
# stand-in and kills any real generation routed through the shared chat panel or
# /api/tasks with a spurious TimeoutError while the render is still in progress.
A2A_POLL_TIMEOUT_SECONDS = float(os.environ.get("A2A_POLL_TIMEOUT_SECONDS", "600"))


class TaskRequest(BaseModel):
    request: str
    owner: str = "미지정"


class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    session_id: str | None = None
    owner: str = "default"
    # `chat_reply()`가 돌려준 `pending_action`(확인이 필요한 동작)을 메시지와 함께
    # 저장해 두면, 탭 전환·새로고침으로 대화가 이 이력에서 다시 만들어질 때도 확인/취소
    # 버튼을 다시 그릴 수 있다(2026-08-19, `ChatReplyRequest.confirmed_skill_id`와 짝).
    pending_action: dict[str, Any] | None = None


class ChatReplyRequest(BaseModel):
    content: str
    owner: str = "미지정"
    # workmate-agent(`assistant_ask`)가 확인이 필요한 동작(예: `analyze_meeting`)을
    # 골랐을 때 `pending_action`으로 돌려준 skill_id/arguments를 그대로 되실어 보내면
    # `assistant_router.py::assistant_ask_workflow()`가 route()를 다시 안 묻고 그
    # Skill을 실제로 실행한다 — Drawer의 확인 배너와 같은 재전송 계약이다(20번 문서
    # G5 대응, 2026-08-19). 채팅 UI가 "확인" 버튼을 누를 때만 채워 보낸다.
    confirmed_skill_id: str | None = None
    confirmed_arguments: dict[str, Any] | None = None


class VideoPromptHandoffRequest(BaseModel):
    art_prompt: dict[str, Any]


class RouteRequest(BaseModel):
    question: str
    locale: str | None = "ko"
    mode: str | None = None


class StoryCreateRequest(BaseModel):
    name: str
    keywords: list[str]
    answer: str


class StoryDraftRequest(StoryCreateRequest):
    relatedLoreIds: list[str] = Field(default_factory=list)
    relatedCodexIds: list[str] = Field(default_factory=list)
    owner: str = "미지정"


class StoryApproveRequest(BaseModel):
    reviewId: str
    draft: StoryDraftRequest


class VideoAgentTaskRequest(BaseModel):
    message: str
    owner: str = "default"


class LocalClient:
    async def send_message(self, agent_url: str, request: dict, headers: dict[str, str] | None = None) -> dict:
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
    "Cat AI Chat": "workmate-agent",
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
GAME_QNA_COMMANDS["/story-review"] = {
    "mode": "story-review",
    "template": "RPG 스토리 초안을 Story Review Workspace에서 검토해줘.",
}


GAME_QNA_SOURCE_LABELS = {
    "dev-guide": "Source: Guide (planning / art)",
    "lore": "Source: World Lore",
    "catalog": "Source: Catalog (game content)",
    "codex": "Source: Codex (characters / monsters / items)",
}


def parse_game_qna_command(content: str) -> dict:
    text = content.strip()
    video_alias = re.fullmatch(r"/\?\s+video(?:\s+(.*))?", text, re.IGNORECASE)
    if video_alias:
        config = GAME_QNA_COMMANDS["/art"]
        return {
            "kind": "request",
            "mode": config["mode"],
            "content": (video_alias.group(1) or "").strip() or config["template"],
            "command": "/art",
        }
    if re.fullmatch(r"/(?:\?|help)", text, re.IGNORECASE):
        return {"kind": "help", "commands": list(GAME_QNA_COMMANDS)}
    match = re.fullmatch(r"/(planning|art|lore|catalog|codexbook|story-review)(?:\s+(.*))?", text, re.IGNORECASE)
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


def game_qna_agent_message(command: dict) -> str:
    if command.get("command") == "/art":
        return f"/art {command['content']}"
    return command["content"]


def _show_art_prompt_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " · ".join(f"{key}: {_show_art_prompt_value(item)}" for key, item in value.items())
    return str(value) if value is not None else "확인 필요"


def format_art_prompt_for_video(prompt: dict[str, Any]) -> str:
    """video-agent는 자유 텍스트 브리핑만 받는다(BriefIntakeAgent) — 구조화 JSON을 읽는
    경로가 없어서, 프론트엔드의 art-prompt-utils.ts formatArtPromptForChat와 같은 포맷으로
    풀어서 보낸다.
    """
    lines = [
        "아트 프롬프트 초안",
        "",
        f"스토리 맥락: {_show_art_prompt_value(prompt.get('story') or prompt.get('스토리 맥락', '확인 필요'))}",
        f"인물상: {_show_art_prompt_value(prompt.get('character') or prompt.get('인물상', '확인 필요'))}",
        f"역할·갈등: {_show_art_prompt_value(prompt.get('context') or prompt.get('갈등', '확인 필요'))}",
    ]
    if prompt.get("nearby"):
        lines.append(f"주변 인물·세력: {_show_art_prompt_value(prompt['nearby'])}")
    if prompt.get("prompt"):
        lines.append(f"연출 방향: {_show_art_prompt_value(prompt['prompt'])}")
    if prompt.get("카메라 구도"):
        lines.append(f"카메라: {_show_art_prompt_value(prompt['카메라 구도'])}")
    if prompt.get("조명"):
        lines.append(f"조명·분위기: {_show_art_prompt_value(prompt['조명'])}")
    return "\n".join(lines)


def build_video_handoff_request(art_prompt: dict[str, Any]) -> dict:
    request = build_agent_request("video-agent", format_art_prompt_for_video(art_prompt))
    request["context"] = {"source": "game-qna"}
    return request


def resolve_chat_agent_fallback(agent_name: str, content: str) -> str:
    if agent_name == "Workmate AI" and re.search(r"홍길동|전우치|세계관|스토리|lore|game|게임", content, re.IGNORECASE):
        return "game-qna-agent"
    return CHAT_AGENT_NAMES.get(agent_name, agent_name)


async def resolve_chat_agent(agent_name: str, content: str) -> str:
    command = parse_game_qna_command(content)
    if command["kind"] in {"help", "request"} and content.strip().startswith("/"):
        return "game-qna-agent"
    routed = await router.select(f"사용자 요청:\n{content}")
    if routed and routed["selected_agents"]:
        return routed["selected_agents"][0]
    return resolve_chat_agent_fallback(agent_name, content)


def build_agent_request(agent_name: str, message: str, mode: str | None = None) -> dict:
    request = {
        "message": message,
        "locale": "ko",
        "system_prompt": get_agent_system_prompt(agent_name),
    }
    if agent_name == "workmate-agent":
        request["skill_id"] = "assistant_ask"
    if mode is not None:
        request["mode"] = mode
    return request


def display_agent_name(agent_name: str) -> str:
    return next((label for label, key in CHAT_AGENT_NAMES.items() if key == agent_name), agent_name)


registry = AgentRegistry.from_environment(os.environ)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/game-qna/art-prompts/send-to-video")
async def send_art_prompt_to_video(payload: VideoPromptHandoffRequest) -> dict:
    configured_card = next(card for card in cards if card.name == "video-agent")
    live_cards = await registry.refresh() if os.getenv("LIVE_AGENT_DISCOVERY", "false").lower() == "true" else {}
    card = live_cards.get("video-agent", configured_card)
    try:
        result = await A2AClient(poll_timeout=A2A_POLL_TIMEOUT_SECONDS).send_message(
            card.url,
            build_video_handoff_request(payload.art_prompt),
            headers=registry.headers("video-agent"),
        )
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": result.get("status", "succeeded"), "answer": result.get("answer") or result.get("summary", ""), "agent": "video-agent"}


@app.get("/api/agents")
def list_agents() -> list[AgentCard]:
    return cards


@app.get("/api/chats/{agent_name}/messages")
def list_chat_messages(agent_name: str, session_id: str | None = None, owner: str = "default") -> list[dict[str, Any]]:
    return conversation_store.list_messages(agent_name, session_id, owner)


@app.get("/api/chats/{agent_name}/session")
def get_chat_session(agent_name: str, owner: str = "default") -> dict:
    session_id = conversation_store.current_session(agent_name, owner)
    return {"session_id": session_id, "messages": conversation_store.list_messages(agent_name, session_id, owner)}


@app.post("/api/chats/{agent_name}/reset")
def reset_chat_session(agent_name: str, owner: str = "default") -> dict[str, str]:
    return {"session_id": conversation_store.reset(agent_name, owner)}


@app.post("/api/chats/{agent_name}/messages", status_code=201)
def save_chat_message(agent_name: str, payload: ChatMessageRequest) -> dict[str, Any]:
    return conversation_store.append(
        agent_name, payload.role, payload.content, payload.session_id, payload.owner, pending_action=payload.pending_action
    )


@app.post("/api/chats/{agent_name}/reply")
async def chat_reply(agent_name: str, payload: ChatReplyRequest) -> dict:
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Message is required")
    card_name = await resolve_chat_agent(agent_name, payload.content)
    configured_card = next((card for card in cards if card.name == card_name), None)
    if configured_card is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    live_cards = await registry.refresh() if os.getenv("LIVE_AGENT_DISCOVERY", "false").lower() == "true" else {}
    card = live_cards.get(card_name, configured_card)
    client = A2AClient(poll_timeout=A2A_POLL_TIMEOUT_SECONDS) if live_cards else LocalClient()
    command = parse_game_qna_command(payload.content) if card_name == "game-qna-agent" else None
    if command and command["kind"] == "help":
        return {"answer": "사용 가능한 Game Q&A 명령어: " + ", ".join(command["commands"]), "agent": card_name, "status": "succeeded"}
    request = build_agent_request(card_name, game_qna_agent_message(command) if command else payload.content)
    request["owner"] = payload.owner
    if payload.confirmed_skill_id:
        # 확인 버튼 재전송 — Data Part에 그대로 실어 workmate-agent가 route()를
        # 다시 안 묻고 바로 실행하게 한다(위 `ChatReplyRequest` 참고).
        request["confirmed_skill_id"] = payload.confirmed_skill_id
        request["confirmed_arguments"] = payload.confirmed_arguments or {}
    if card_name == "game-qna-agent":
        request["mode"] = command["mode"] if command else "lore"
    try:
        result = await client.send_message(card.url, request, headers=registry.headers(card_name))
        review = await router.review(payload.content, card_name, result.get("answer") or result.get("summary") or "") if hasattr(router, "review") else None
        replacement = review.get("replacement_agent") if review and not review["accepted"] else None
        if replacement and replacement != card_name:
            replacement_card = live_cards.get(replacement) if live_cards else next((item for item in cards if item.name == replacement), None)
            if replacement_card:
                card_name = replacement
                card = replacement_card
                command = parse_game_qna_command(payload.content) if card_name == "game-qna-agent" else None
                request = build_agent_request(card_name, game_qna_agent_message(command) if command else payload.content)
                if card_name == "game-qna-agent":
                    request["mode"] = command["mode"] if command else "lore"
                result = await client.send_message(card.url, request, headers=registry.headers(card_name))
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    answer = result.get("answer") or result.get("summary") or "응답을 받지 못했습니다."
    effective_mode = result.get("mode") or request.get("mode")
    if card_name == "game-qna-agent" and not answer.startswith("[Source:"):
        source_label = GAME_QNA_SOURCE_LABELS.get(effective_mode, "Source: Game Q&A")
        answer = f"[{source_label}]\n{answer}"
    pending_action = result.get("pending_action")
    if pending_action and not (isinstance(pending_action, dict) and pending_action.get("skill_id")):
        # `pending_action`은 있지만 프론트가 재전송에 필요한 `skill_id`를 읽을 수
        # 없는 모양이면(예상 밖 응답) 버튼을 못 그려주니, 예전처럼 텍스트 안내로만
        # 폴백한다 — 문구는 `workmate-agent/tools/m51_legacy_adapter.py::
        # _PENDING_ACTION_NOTICE`와 같다.
        answer = f"{answer}\n\n(이 요청은 실행 확인이 필요합니다 — Workmate 화면에서 직접 진행해 주세요.)"
        pending_action = None
    response_body = {
        "answer": answer,
        "agent": card_name,
        "mode": effective_mode,
        "command": command.get("command") if command and command["kind"] == "request" else None,
        "status": result.get("status", "succeeded"),
        # `assistant_ask`가 확인이 필요한 동작을 골랐을 때의 {skill_id, arguments} —
        # 채팅 UI가 이 값을 그대로 `ChatReplyRequest.confirmed_skill_id`/
        # `confirmed_arguments`에 실어 재전송하면 실제로 실행된다(위 참고,
        # 2026-08-19 G5 대응: 확인/취소 버튼).
        "pending_action": pending_action,
    }
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    task_log_store.append(
        agent=display_agent_name(card_name),
        task_name=payload.content.strip(),
        owner=payload.owner,
        status="완료" if response_body["status"] == "succeeded" else "실패",
        result_summary=answer[:240],
        recorded_at=now,
        reset_id=task_log_store.current_reset_id(work_date=now.date().isoformat()),
    )
    task = result.get("task") or {}
    unresolved_scenes = (task.get("status") or {}).get("unresolvedScenes")
    if unresolved_scenes:
        response_body["taskId"] = task.get("id")
        response_body["unresolvedScenes"] = unresolved_scenes
    return response_body


@app.get("/api/policies/task-logs")
def list_task_logs(
    work_date: str,
    owner: str | None = None,
    agent: str | None = None,
    reset_id: str | None = None,
    offset: int = 0,
    limit: int = 30,
) -> dict:
    logs = task_log_store.list_logs(work_date=work_date, owner=owner, agent=agent, reset_id=reset_id, offset=offset, limit=limit)
    return {"items": logs, "next_offset": offset + len(logs) if len(logs) == min(max(limit, 1), 100) else None}


@app.get("/api/policies/task-log-owners")
def list_task_log_owners() -> list[str]:
    return task_log_store.owners()


@app.post("/api/policies/task-logs/reset", status_code=201)
def reset_task_logs(work_date: str) -> dict:
    return task_log_store.reset(work_date=work_date)


@app.post("/api/route")
async def route_request(payload: RouteRequest) -> dict:
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question is required")
    return await chat_reply("Cat AI Chat", ChatReplyRequest(content=payload.question))


def catalog_base_url() -> str:
    catalog_url = os.getenv("GAME_QNA_AGENT_URL", os.getenv("GAME_QA_AGENT_URL", "http://game-qa-agent:3000/message:send"))
    return catalog_url.rsplit("/message:send", 1)[0].removesuffix("/a2a").rstrip("/")


async def post_catalog(path: str, payload: dict) -> dict:
    try:
        token = os.getenv("GAME_QNA_SERVICE_TOKEN") or os.getenv("API_KEY")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        timeout = float(os.getenv("CATALOG_API_TIMEOUT_SECONDS", "45"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{catalog_base_url()}{path}", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Catalog story API unavailable: {exc}") from exc


@app.post("/api/stories/review")
async def review_story(payload: StoryDraftRequest) -> dict:
    reviewed = await post_catalog("/api/story-review", payload.model_dump(exclude={"owner"}))
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    task_log_store.append(agent="Game Q&A", task_name=f"스토리 검토: {payload.name}", owner=payload.owner, status="검토 중", result_summary="RPG 스토리 검토를 실행했습니다.", recorded_at=now, reset_id=task_log_store.current_reset_id(work_date=now.date().isoformat()))
    return reviewed


@app.post("/api/stories/approve", status_code=201)
async def approve_story(payload: StoryApproveRequest) -> dict:
    return await post_catalog("/api/story-approve", {"reviewId": payload.reviewId, "draft": payload.draft.model_dump(exclude={"owner"})})


@app.post("/api/tasks", status_code=202)
async def create_task(payload: TaskRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    live_cards = await registry.refresh() if os.getenv("LIVE_AGENT_DISCOVERY", "false").lower() == "true" else {}
    active_cards = list(live_cards.values()) or cards
    client = A2AClient(poll_timeout=A2A_POLL_TIMEOUT_SECONDS) if live_cards else LocalClient()
    orchestrator = Orchestrator(client, store, router=router)
    selected = await orchestrator.select(payload.request, active_cards)
    task = store.create(payload.request, [card.name for card in selected])
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    reset_id = task_log_store.current_reset_id(work_date=now.date().isoformat())
    for card in selected:
        task_log_store.append(
            agent=display_agent_name(card.name),
            task_name=payload.request,
            owner=payload.owner,
            status="진행 중",
            result_summary="Task 실행을 시작했습니다.",
            recorded_at=now,
            reset_id=reset_id,
        )

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
                results.append(await orchestrator.client.send_message(card.url, request, headers=registry.headers(card.name)))
            store.update(task.task_id, status="succeeded", result={"results": results})
            completed_at = datetime.now(ZoneInfo("Asia/Seoul"))
            for card in selected:
                task_log_store.append(agent=display_agent_name(card.name), task_name=payload.request, owner=payload.owner, status="완료", result_summary="Task 실행이 완료되었습니다.", recorded_at=completed_at, reset_id=task_log_store.current_reset_id(work_date=completed_at.date().isoformat()))
        except A2AError as exc:
            error = f"{exc.status}: {exc.message}"
            if exc.request_id:
                error += f" (request_id={exc.request_id})"
            store.update(task.task_id, status="failed", result={"results": results}, error=error)
            failed_at = datetime.now(ZoneInfo("Asia/Seoul"))
            for card in selected:
                task_log_store.append(agent=display_agent_name(card.name), task_name=payload.request, owner=payload.owner, status="실패", result_summary=error[:240], recorded_at=failed_at, reset_id=task_log_store.current_reset_id(work_date=failed_at.date().isoformat()))
        except Exception as exc:
            store.update(task.task_id, status="failed", result={"results": results}, error=str(exc))
            failed_at = datetime.now(ZoneInfo("Asia/Seoul"))
            for card in selected:
                task_log_store.append(agent=display_agent_name(card.name), task_name=payload.request, owner=payload.owner, status="실패", result_summary=str(exc)[:240], recorded_at=failed_at, reset_id=task_log_store.current_reset_id(work_date=failed_at.date().isoformat()))

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
            results.append(await LocalClient().send_message(card.url, build_agent_request(card.name, task.request), headers=registry.headers(card.name)))
        store.update(task_id, status="succeeded", result={"results": results})

    background_tasks.add_task(rerun)
    return {"task_id": task_id, "status": "running"}


@app.post("/api/video-agent/tasks/{task_id}/scenes/{scene_id}/resume")
async def resume_video_scene(task_id: str, scene_id: str, file: UploadFile = File(...)) -> dict:
    config = registry.config("video-agent")
    contents = await file.read()
    resume_url = f"{config.base_url}/tasks/{task_id}/scenes/{scene_id}/resume"
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                resume_url,
                files={"file": (file.filename, contents, file.content_type)},
                headers=registry.headers("video-agent"),
            )
        if response.is_error:
            try:
                raise A2AError.from_payload(response.json(), response.status_code)
            except ValueError:
                raise RuntimeError(f"video-agent HTTP {response.status_code}: {response.text}") from None
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return response.json()


@app.post("/api/video-agent/tasks")
async def create_video_agent_task(payload: VideoAgentTaskRequest) -> dict:
    try:
        result = await video_agent_client.send_message(registry, payload.message, user_id=payload.owner)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    task_log_store.append(
        agent="Video Generation",
        task_name=payload.message.strip(),
        owner=payload.owner,
        status="진행 중",
        result_summary="영상 생성 작업을 시작했습니다.",
        recorded_at=now,
        reset_id=task_log_store.current_reset_id(work_date=now.date().isoformat()),
    )
    return result


@app.get("/api/video-agent/tasks")
async def list_video_agent_tasks(owner: str, limit: int = 20, offset: int = 0) -> dict:
    try:
        return await video_agent_client.list_tasks(registry, owner, limit=limit, offset=offset)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/video-agent/tasks/{task_id}/detail")
async def get_video_agent_task_detail(task_id: str) -> dict:
    try:
        return await video_agent_client.get_task_detail(registry, task_id)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/video-agent/tasks/{task_id}")
async def get_video_agent_task(task_id: str) -> dict:
    try:
        return await video_agent_client.get_task(registry, task_id)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/video-agent/tasks/{task_id}/cancel")
async def cancel_video_agent_task(task_id: str) -> dict:
    try:
        return await video_agent_client.cancel_task(registry, task_id)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/api/video-agent/tasks/{task_id}")
async def delete_video_agent_task(task_id: str) -> dict:
    try:
        return await video_agent_client.delete_task(registry, task_id)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/video-agent/veo-usage")
async def get_veo_usage() -> dict:
    try:
        return await video_agent_client.get_veo_usage(registry)
    except A2AError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict()["error"]) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
