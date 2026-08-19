"""Local stand-in for the standalone workmate-agent REST API (port 8100).

frontend/src/workmate/api.ts talks to a separate, non-A2A REST server that only
exists when her real workmate-agent is run directly on her machine
(`python -m app.server`) - it isn't the A2A mock in app.py (port 8001, used by
main-agent's orchestrator routing), and it isn't checked into this repo at all.
Until her updated workmate-agent repo is pulled in, this fills in the same
contract (frontend/src/workmate/types.ts) with in-memory mock data so the
Today Briefing / Weekly Report / task / meeting / proposal panels render
instead of showing "Failed to fetch" - not a replacement for the real thing.

Run: uvicorn rest_stub_server:app --host 127.0.0.1 --port 8100
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI(title="workmate-agent REST stub")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_assignee(x_workmate_assignee: str | None = Header(default=None)) -> str:
    if not x_workmate_assignee:
        raise HTTPException(status_code=401, detail="X-Workmate-Assignee header is required")
    from urllib.parse import unquote

    return unquote(x_workmate_assignee)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# skill-chat (Today Briefing / Weekly Report / meeting search / meeting analysis)
# ---------------------------------------------------------------------------

class SkillChatRequest(BaseModel):
    skill_id: str
    input: dict[str, Any] = {}


def _daily_briefing_result() -> dict[str, Any]:
    today = datetime.now(timezone.utc)
    return {
        "date": today.date().isoformat(),
        "summary": "(stub) 오늘 처리할 업무를 요약했습니다. 실제 workmate-agent가 아직 연결되지 않았습니다.",
        "calendar_events": [
            {"event_id": "stub-event-1", "title": "(stub) 데일리 스크럼", "starts_at": today.replace(hour=10, minute=0).isoformat(), "ends_at": today.replace(hour=10, minute=30).isoformat(), "related_task_ids": []},
        ],
        "important_signals": [
            {"type": "email", "source_id": "stub-mail-1", "summary": "(stub) 실데이터 연결 전 표시되는 예시 신호입니다.", "related_task_ids": []},
        ],
        "priorities": [
            {"rank": 1, "task_id": "stub-task-1", "title": "(stub) 예시 우선순위 업무", "score": 80, "reasons": ["stub 데이터"]},
        ],
        "source_refs": [],
    }


def _priority_ranking_result() -> dict[str, Any]:
    return {
        "calculated_at": now_iso(),
        "priorities": _daily_briefing_result()["priorities"],
        "changes": [],
        "source_refs": [],
    }


def _weekly_report_result() -> dict[str, Any]:
    today = datetime.now(timezone.utc)
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return {
        "period": {"start": start.date().isoformat(), "end": end.date().isoformat()},
        "summary": "(stub) 이번 주 업무 보고 요약입니다. 실제 workmate-agent가 아직 연결되지 않았습니다.",
        "completed": [{"task_id": "stub-task-2", "title": "(stub) 완료된 업무", "status": "done", "summary": None, "due_at": None, "source_refs": []}],
        "in_progress": [{"task_id": "stub-task-3", "title": "(stub) 진행 중인 업무", "status": "in_progress", "summary": None, "due_at": None, "source_refs": []}],
        "delayed": [],
        "unresolved_issues": [],
        "next_week_plans": [{"title": "(stub) 다음 주 계획 예시", "kind": "planned", "source_refs": []}],
        "source_refs": [],
    }


def _search_meetings_result(query: str) -> dict[str, Any]:
    return {
        "answer": f"(stub) '{query}'에 대한 검색 결과를 찾지 못했습니다 - 실제 workmate-agent가 아직 연결되지 않았습니다.",
        "sources": [],
        "insufficient_evidence": True,
    }


SKILL_TASKS: dict[str, dict[str, Any]] = {}


@app.post("/api/v1/internal/skill-chat/messages")
def skill_chat_send(payload: SkillChatRequest, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    skill_id = payload.skill_id
    task_id = f"stub-task-{uuid.uuid4()}"

    if skill_id == "daily_briefing":
        typed = {"type": "daily_briefing", "data": _daily_briefing_result()}
    elif skill_id == "rank_priorities":
        typed = {"type": "priority_ranking", "data": _priority_ranking_result()}
    elif skill_id == "weekly_report":
        typed = {"type": "weekly_report", "data": _weekly_report_result()}
    elif skill_id == "search_meetings":
        typed = {"type": "grounded_answer", "data": _search_meetings_result(str(payload.input.get("query", "")))}
    elif skill_id == "analyze_meeting":
        # usePollingSkillRunner expects state="submitted" then polls the task.
        SKILL_TASKS[task_id] = {"skill_id": skill_id, "meeting_id": payload.input.get("meeting_id")}
        return {
            "skill_id": skill_id,
            "task_id": task_id,
            "state": "submitted",
            "artifact": {"name": skill_id, "description": "", "text": "", "data": None, "markdown": None, "mock": True, "business_result": False},
            "warnings": [],
        }
    else:
        raise HTTPException(status_code=400, detail=f"Unknown skill_id: {skill_id}")

    return {
        "skill_id": skill_id,
        "task_id": task_id,
        "state": "completed",
        "artifact": {"name": skill_id, "description": "", "text": "", "data": typed, "markdown": None, "mock": True, "business_result": False},
        "warnings": [],
    }


@app.get("/api/v1/internal/skill-chat/tasks/{task_id}")
def skill_chat_task(task_id: str, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    # Stub completes immediately on first poll - real analyze_meeting is async STT+LLM.
    return {
        "id": task_id,
        "status": {"state": "TASK_STATE_COMPLETED"},
        "artifacts": [{"artifactId": f"artifact-{task_id}", "metadata": {"mock": True, "business_result": False, "warnings": []}}],
    }


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------

TASKS: dict[str, dict[str, Any]] = {}


class TaskCreate(BaseModel):
    title: str
    status: str = "todo"
    priority_hint: float | None = None
    due_at: str | None = None
    source_type: str = "manual"


class TaskUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    priority_hint: float | None = None
    due_at: str | None = None


@app.get("/api/v1/tasks")
def list_tasks(status: str | None = None, assignee: str = Depends(require_assignee)) -> list[dict[str, Any]]:
    items = list(TASKS.values())
    if status:
        items = [item for item in items if item["status"] == status]
    return items


@app.post("/api/v1/tasks")
def create_task(payload: TaskCreate, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    task_id = f"stub-task-{uuid.uuid4()}"
    task = {"task_id": task_id, **payload.model_dump()}
    TASKS[task_id] = task
    return task


@app.patch("/api/v1/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdate, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.update({k: v for k, v in payload.model_dump().items() if v is not None})
    return task


@app.delete("/api/v1/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, assignee: str = Depends(require_assignee)) -> None:
    TASKS.pop(task_id, None)


# ---------------------------------------------------------------------------
# meetings
# ---------------------------------------------------------------------------

MEETINGS: dict[str, dict[str, Any]] = {}


class MeetingCreate(BaseModel):
    title: str
    started_at: str | None = None
    meeting_id: str | None = None


@app.get("/api/v1/meetings")
def list_meetings(assignee: str = Depends(require_assignee)) -> list[dict[str, Any]]:
    return list(MEETINGS.values())


@app.post("/api/v1/meetings")
def create_meeting(payload: MeetingCreate, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    meeting_id = payload.meeting_id or f"stub-meeting-{uuid.uuid4()}"
    meeting = {"meeting_id": meeting_id, "title": payload.title, "started_at": payload.started_at or now_iso()}
    MEETINGS[meeting_id] = meeting
    return meeting


@app.get("/api/v1/meetings/{meeting_id}")
def get_meeting(meeting_id: str, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    meeting = MEETINGS.get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@app.delete("/api/v1/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, assignee: str = Depends(require_assignee)) -> None:
    MEETINGS.pop(meeting_id, None)


@app.get("/api/v1/meetings/{meeting_id}/transcript")
def get_transcript(meeting_id: str, assignee: str = Depends(require_assignee)) -> list[dict[str, Any]]:
    return []


@app.post("/api/v1/meetings/{meeting_id}/recordings")
async def upload_recording(meeting_id: str, request: Request, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"recording_id": f"stub-recording-{uuid.uuid4()}", "meeting_id": meeting_id, "uploaded_at": now_iso()}


@app.get("/api/v1/meetings/{meeting_id}/analysis")
def get_analysis(meeting_id: str, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"meeting_id": meeting_id, "summary": "(stub) 분석 결과가 없습니다.", "action_items": [], "transcript_ref": "", "source_refs": []}


class ActionApprove(BaseModel):
    title: str
    evidence_text: str


@app.post("/api/v1/meetings/{meeting_id}/actions/{action_item_id}/approve")
def approve_action(meeting_id: str, action_item_id: str, payload: ActionApprove, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"action_item_id": action_item_id, "approval_status": "approved", "task_id": f"stub-task-{uuid.uuid4()}", "idempotent": False}


class ActionReviewDecision(BaseModel):
    action_item_id: str
    decision: Literal["approve", "edit", "reject"]
    changes: dict[str, Any] | None = None


class ActionsReview(BaseModel):
    decisions: list[ActionReviewDecision]


@app.post("/api/v1/meetings/{meeting_id}/actions:review")
def review_actions(meeting_id: str, payload: ActionsReview, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    results = [
        {"action_item_id": item.action_item_id, "decision": item.decision, "approval_status": "approved" if item.decision == "approve" else item.decision, "task_id": f"stub-task-{uuid.uuid4()}" if item.decision == "approve" else None}
        for item in payload.decisions
    ]
    return {"results": results}


# ---------------------------------------------------------------------------
# proposals / gmail / calendar / google auth
# ---------------------------------------------------------------------------

class ProposalReview(BaseModel):
    decision: Literal["approve", "ignore"]
    task: dict[str, Any] | None = None
    allow_similar_duplicate: bool = False
    message_id: str | None = None
    calendar_id: str | None = None
    event_id: str | None = None


@app.post("/api/v1/email-task-proposals:review")
def review_email_proposal(payload: ProposalReview, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"decision": payload.decision, "source_type": "email", "source_id": payload.message_id or "", "created": payload.decision == "approve"}


@app.post("/api/v1/calendar-task-proposals:review")
def review_calendar_proposal(payload: ProposalReview, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"decision": payload.decision, "source_type": "calendar", "source_id": payload.event_id or "", "created": payload.decision == "approve"}


@app.post("/api/v1/dev/gmail-sync")
def gmail_sync(limit: int = 5, assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"fetched": 0, "published": [], "skipped": [], "note": "stub server - no real Gmail connection"}


@app.post("/api/v1/dev/calendar-sync")
def calendar_sync(assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"fetched": 0, "published": [], "skipped": [], "note": "stub server - no real Calendar connection"}


@app.get("/api/v1/auth/google/status")
def google_status(assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"connected": False}


@app.get("/api/v1/auth/google/start")
def google_start(assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"authorization_url": "about:blank"}


@app.post("/api/v1/auth/google/disconnect")
def google_disconnect(assignee: str = Depends(require_assignee)) -> dict[str, Any]:
    return {"connected": False}


@app.get("/api/v1/notifications/stream")
async def notifications_stream(assignee: str = Depends(require_assignee)):
    from starlette.responses import StreamingResponse

    async def empty_stream():
        return
        yield b""  # pragma: no cover - keeps this an async generator

    return StreamingResponse(empty_stream(), media_type="text/event-stream")
