from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class AgentSkill(BaseModel):
    id: str
    name: str


class AgentCapabilities(BaseModel):
    streaming: bool = False


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    skills: list[AgentSkill] = Field(default_factory=list)
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    streaming: bool = False


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent: str | None = None
    type: str
    message: str


class TaskRecord(BaseModel):
    task_id: str
    request: str
    selected_agents: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.QUEUED
    events: list[TaskEvent] = Field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
