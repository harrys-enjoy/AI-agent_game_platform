from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class AgentSkill(BaseModel):
    id: str
    name: str


class AgentCapabilities(BaseModel):
    streaming: bool = False


class AgentInterface(BaseModel):
    url: str
    protocol_binding: str = Field(alias="protocolBinding")
    protocol_version: str = Field(alias="protocolVersion")

    model_config = {"populate_by_name": True}


class AgentCard(BaseModel):
    name: str
    description: str
    url: str | None = None
    skills: list[AgentSkill] = Field(default_factory=list)
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    streaming: bool = False
    supported_interfaces: list[AgentInterface] = Field(default_factory=list, alias="supportedInterfaces")
    security_schemes: dict[str, dict] = Field(default_factory=dict, alias="securitySchemes")

    model_config = {"populate_by_name": True}


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
