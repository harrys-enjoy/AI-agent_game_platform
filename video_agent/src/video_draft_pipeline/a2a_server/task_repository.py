"""SQLite persistence for task records.

`TaskStore` (tasks.py) was in-memory only, so every generated video's task
record (state, output URL, which assignee made it) was lost on every
container restart - the video files themselves now survive via the
/app/media volume mount, but nothing pointed back at them. This mirrors
workmate-agent's app/repositories/google_credentials.py: a SQLite file
under .runtime/ (gitignored, volume-mounted so it also survives container
recreation), same file-per-record-type pattern as tasks.sqlite3 there.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from .tasks import TaskRecord

TASK_DB_PATH_ENV = "VIDEO_AGENT_TASK_DB_PATH"
_DEFAULT_DB_PATH = ".runtime/tasks.sqlite3"


class SQLiteTaskRepository:
    """Local-only persistence - no server-side/hosted database involved."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.database_path = str(database_path)
        self._use_uri = self.database_path == ":memory:"
        if not self._use_uri:
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            # Keep one connection alive for the process lifetime so the
            # in-memory database isn't dropped between calls (sqlite3
            # :memory: is per-connection) - same trick as
            # SQLiteGoogleCredentialRepository.
            self._anchor = sqlite3.connect(self.database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    context_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    answer TEXT,
                    detail TEXT,
                    project_id TEXT,
                    unresolved_scenes TEXT,
                    output_video_url TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    artifact_id TEXT,
                    user_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
                """
            )

    def save(self, record: TaskRecord) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO tasks(task_id, context_id, state, answer, detail, project_id,
                    unresolved_scenes, output_video_url, cancel_requested, artifact_id, user_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    context_id=excluded.context_id, state=excluded.state, answer=excluded.answer,
                    detail=excluded.detail, project_id=excluded.project_id,
                    unresolved_scenes=excluded.unresolved_scenes, output_video_url=excluded.output_video_url,
                    cancel_requested=excluded.cancel_requested, artifact_id=excluded.artifact_id,
                    user_id=excluded.user_id, updated_at=excluded.updated_at
                """,
                (
                    record.task_id,
                    record.context_id,
                    record.state,
                    record.answer,
                    record.detail,
                    record.project_id,
                    json.dumps(record.unresolved_scenes) if record.unresolved_scenes is not None else None,
                    record.output_video_url,
                    int(record.cancel_requested),
                    record.artifact_id,
                    record.user_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def load_all(self) -> list[TaskRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM tasks").fetchall()
        return [_row_to_record(row) for row in rows]

    def list_for_user(self, user_id: str) -> list[TaskRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
        return [_row_to_record(row) for row in rows]


def _row_to_record(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        task_id=row["task_id"],
        context_id=row["context_id"],
        state=row["state"],
        answer=row["answer"],
        detail=row["detail"],
        project_id=row["project_id"],
        unresolved_scenes=json.loads(row["unresolved_scenes"]) if row["unresolved_scenes"] else None,
        output_video_url=row["output_video_url"],
        cancel_requested=bool(row["cancel_requested"]),
        artifact_id=row["artifact_id"],
        user_id=row["user_id"],
    )


def task_repository() -> SQLiteTaskRepository:
    """The repository the real running server uses - a local SQLite file
    under .runtime/, volume-mounted so it survives container recreation.
    Not called from tests (they build TaskStore() with no repository, or
    pass their own), so this only ever touches disk in the real container.
    """

    return SQLiteTaskRepository(os.getenv(TASK_DB_PATH_ENV, _DEFAULT_DB_PATH))


__all__ = ["SQLiteTaskRepository", "task_repository", "TASK_DB_PATH_ENV"]
