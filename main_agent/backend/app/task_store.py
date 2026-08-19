import json
import sqlite3
import uuid

from .contracts import TaskEvent, TaskRecord, TaskStatus


class TaskStore:
    def __init__(self, path: str = "main_agent.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.commit()

    def create(self, request: str, selected_agents: list[str]) -> TaskRecord:
        task = TaskRecord(task_id=str(uuid.uuid4()), request=request, selected_agents=selected_agents)
        self._save(task)
        return task

    def get(self, task_id: str) -> TaskRecord | None:
        row = self.db.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
        return TaskRecord.model_validate_json(row[0]) if row else None

    def update(self, task_id: str, **changes) -> TaskRecord:
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        for key, value in changes.items():
            setattr(task, key, TaskStatus(value) if key == "status" else value)
        self._save(task)
        return task

    def append_event(self, task_id: str, event: TaskEvent) -> TaskRecord:
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        task.events.append(event)
        self._save(task)
        return task

    def _save(self, task: TaskRecord) -> None:
        self.db.execute("INSERT OR REPLACE INTO tasks(id,data) VALUES (?,?)", (task.task_id, task.model_dump_json()))
        self.db.commit()
