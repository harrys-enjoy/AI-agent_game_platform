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
from uuid import uuid4

from .tasks import TaskRecord, _now_iso

TASK_DB_PATH_ENV = "VIDEO_AGENT_TASK_DB_PATH"
_DEFAULT_DB_PATH = ".runtime/tasks.sqlite3"


class SQLiteTaskRepository:
    """Local-only persistence - no server-side/hosted database involved."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.database_path = str(database_path)
        self._use_uri = self.database_path == ":memory:"
        # Plain sqlite3.connect(":memory:") gives every connection its own
        # isolated, empty database - a named shared-cache URI is required so
        # repeated _connect() calls (save() then load_all(), etc.) see the
        # same in-memory data. Same trick as SQLiteGoogleCredentialRepository
        # in workmate-agent.
        self._connection_target = (
            f"file:video-agent-tasks-{uuid4().hex}?mode=memory&cache=shared" if self._use_uri else self.database_path
        )
        if not self._use_uri:
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._anchor = sqlite3.connect(self._connection_target, uri=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._connection_target, uri=self._use_uri)
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
            # Migration for DBs created before `brief`/`created_at` existed - CREATE
            # TABLE IF NOT EXISTS above doesn't add columns to an existing table.
            existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
            if "brief" not in existing_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN brief TEXT")
            if "created_at" not in existing_columns:
                # Pre-existing rows have no real creation time on record - fall back
                # to updated_at (better than leaving it NULL and confusing the UI).
                connection.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
                connection.execute("UPDATE tasks SET created_at = updated_at WHERE created_at IS NULL")

    def save(self, record: TaskRecord) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO tasks(task_id, context_id, state, answer, detail, project_id,
                    unresolved_scenes, output_video_url, cancel_requested, artifact_id, user_id, brief,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    context_id=excluded.context_id, state=excluded.state, answer=excluded.answer,
                    detail=excluded.detail, project_id=excluded.project_id,
                    unresolved_scenes=excluded.unresolved_scenes, output_video_url=excluded.output_video_url,
                    cancel_requested=excluded.cancel_requested, artifact_id=excluded.artifact_id,
                    user_id=excluded.user_id, brief=excluded.brief, updated_at=excluded.updated_at
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
                    record.brief,
                    record.created_at,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def delete(self, task_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

    def load_all(self) -> list[TaskRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM tasks").fetchall()
        return [_row_to_record(row) for row in rows]

    def list_for_user(self, user_id: str, limit: int = 20, offset: int = 0) -> tuple[list[TaskRecord], bool]:
        with closing(self._connect()) as connection:
            # Fetch one extra row to detect whether another page exists,
            # without a separate COUNT(*) query.
            rows = connection.execute(
                "SELECT * FROM tasks WHERE user_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (user_id, limit + 1, offset),
            ).fetchall()
        has_more = len(rows) > limit
        return [_row_to_record(row) for row in rows[:limit]], has_more


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
        brief=row["brief"] if "brief" in row.keys() else None,
        created_at=row["created_at"] if "created_at" in row.keys() and row["created_at"] else _now_iso(),
    )


def task_repository() -> SQLiteTaskRepository:
    """The repository the real running server uses - a local SQLite file
    under .runtime/, volume-mounted so it survives container recreation.
    Not called from tests (they build TaskStore() with no repository, or
    pass their own), so this only ever touches disk in the real container.
    """

    return SQLiteTaskRepository(os.getenv(TASK_DB_PATH_ENV, _DEFAULT_DB_PATH))


__all__ = ["SQLiteTaskRepository", "task_repository", "TASK_DB_PATH_ENV"]
