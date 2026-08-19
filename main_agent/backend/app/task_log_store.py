from datetime import datetime, timezone
import sqlite3
import uuid
from zoneinfo import ZoneInfo


SEOUL = ZoneInfo("Asia/Seoul")


class TaskLogStore:
    """Append-only execution log for the Policies task history screen."""

    def __init__(self, path: str = "main_agent.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS task_logs (
                log_id TEXT PRIMARY KEY,
                recorded_at TEXT NOT NULL,
                work_date TEXT NOT NULL,
                agent TEXT NOT NULL,
                task_name TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                result_summary TEXT NOT NULL,
                reset_id TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS task_log_resets (
                reset_id TEXT PRIMARY KEY,
                reset_at TEXT NOT NULL,
                work_date TEXT NOT NULL
            )"""
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_date ON task_logs(work_date, recorded_at DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_owner ON task_logs(owner, recorded_at DESC)")
        self.db.commit()

    def append(
        self,
        *,
        agent: str,
        task_name: str,
        owner: str,
        status: str,
        result_summary: str,
        recorded_at: datetime | None = None,
        reset_id: str = "daily",
    ) -> dict:
        timestamp = recorded_at or datetime.now(timezone.utc)
        local_timestamp = timestamp.astimezone(SEOUL)
        log = {
            "log_id": str(uuid.uuid4()),
            "recorded_at": local_timestamp.isoformat(),
            "work_date": local_timestamp.date().isoformat(),
            "agent": agent,
            "task_name": task_name,
            "owner": owner or "미지정",
            "status": status,
            "result_summary": result_summary,
            "reset_id": reset_id,
        }
        self.db.execute(
            "INSERT INTO task_logs(log_id, recorded_at, work_date, agent, task_name, owner, status, result_summary, reset_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(log.values()),
        )
        self.db.commit()
        return log

    def reset(self, *, work_date: str, reset_at: datetime | None = None) -> dict:
        timestamp = (reset_at or datetime.now(timezone.utc)).astimezone(SEOUL)
        reset = {"reset_id": str(uuid.uuid4()), "reset_at": timestamp.isoformat(), "work_date": work_date}
        self.db.execute(
            "INSERT INTO task_log_resets(reset_id, reset_at, work_date) VALUES (?, ?, ?)",
            tuple(reset.values()),
        )
        self.db.commit()
        return reset

    def list_logs(
        self,
        *,
        work_date: str,
        owner: str | None = None,
        agent: str | None = None,
        reset_id: str | None = None,
        offset: int = 0,
        limit: int = 30,
    ) -> list[dict]:
        conditions = ["work_date = ?"]
        params: list[str | int] = [work_date]
        if owner:
            conditions.append("owner = ?")
            params.append(owner)
        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if reset_id:
            conditions.append("reset_id = ?")
            params.append(reset_id)
        params.extend([min(max(limit, 1), 100), max(offset, 0)])
        rows = self.db.execute(
            f"SELECT * FROM task_logs WHERE {' AND '.join(conditions)} ORDER BY recorded_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def list_resets(self, *, work_date: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT reset_id, reset_at, work_date FROM task_log_resets WHERE work_date = ? ORDER BY reset_at DESC",
            (work_date,),
        ).fetchall()
        return [dict(row) for row in rows]

    def owners(self) -> list[str]:
        rows = self.db.execute("SELECT DISTINCT owner FROM task_logs WHERE owner <> '' ORDER BY owner").fetchall()
        return [row[0] for row in rows]

    def current_reset_id(self, *, work_date: str) -> str:
        row = self.db.execute(
            "SELECT reset_id FROM task_log_resets WHERE work_date = ? ORDER BY reset_at DESC LIMIT 1",
            (work_date,),
        ).fetchone()
        return row[0] if row else "daily"
