import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass
class TaskRecord:
    task_id: str
    context_id: str = ""
    state: str = "TASK_STATE_SUBMITTED"
    answer: str | None = None
    detail: str | None = None
    project_id: str | None = None
    unresolved_scenes: list[dict] | None = None
    output_video_url: str | None = None
    cancel_requested: bool = False
    artifact_id: str | None = None
    user_id: str | None = None


class TaskRepository(Protocol):
    """Persistence contract for TaskStore - see task_repository.py."""

    def save(self, record: TaskRecord) -> None: ...

    def load_all(self) -> list[TaskRecord]: ...

    def list_for_user(self, user_id: str) -> list[TaskRecord]: ...


class TaskStore:
    def __init__(self, repository: TaskRepository | None = None) -> None:
        self._repository = repository
        self._tasks: dict[str, TaskRecord] = {}
        self._message_ids: dict[str, str | None] = {}
        if repository is not None:
            for record in repository.load_all():
                self._tasks[record.task_id] = record

    def _persist(self, task_id: str) -> None:
        if self._repository is not None:
            self._repository.save(self._tasks[task_id])

    def create(self, user_id: str | None = None) -> TaskRecord:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        record = TaskRecord(task_id=task_id, context_id=f"ctx_{uuid.uuid4().hex[:8]}", user_id=user_id)
        self._tasks[task_id] = record
        self._persist(task_id)
        return record

    def list_for_user(self, user_id: str) -> list[TaskRecord]:
        """Most-recent-first, matching the repository's own ordering."""

        if self._repository is not None:
            return self._repository.list_for_user(user_id)
        return [record for record in reversed(self._tasks.values()) if record.user_id == user_id]

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def mark_working(self, task_id: str) -> None:
        self._tasks[task_id].state = "TASK_STATE_WORKING"
        self._persist(task_id)

    def mark_completed(self, task_id: str, answer: str, output_video_url: str | None = None) -> None:
        record = self._tasks[task_id]
        record.state = "TASK_STATE_COMPLETED"
        record.answer = answer
        record.output_video_url = output_video_url
        record.artifact_id = f"artifact_{uuid.uuid4().hex[:8]}"
        self._persist(task_id)

    def mark_failed(self, task_id: str, answer: str, detail: str | None = None) -> None:
        record = self._tasks[task_id]
        record.state = "TASK_STATE_FAILED"
        record.answer = answer
        record.detail = detail
        self._persist(task_id)

    def mark_input_required(self, task_id: str, answer: str) -> None:
        record = self._tasks[task_id]
        record.state = "TASK_STATE_INPUT_REQUIRED"
        record.answer = answer
        record.artifact_id = f"artifact_{uuid.uuid4().hex[:8]}"
        self._persist(task_id)

    def request_cancel(self, task_id: str) -> None:
        record = self._tasks[task_id]
        record.cancel_requested = True
        record.state = "TASK_STATE_CANCELED"
        self._persist(task_id)

    def set_project_id(self, task_id: str, project_id: str) -> None:
        self._tasks[task_id].project_id = project_id
        self._persist(task_id)

    def set_unresolved_scenes(self, task_id: str, scenes: list[dict]) -> None:
        self._tasks[task_id].unresolved_scenes = scenes
        self._persist(task_id)

    def register_message_id(self, message_id: str, task_id: str) -> None:
        self._message_ids[message_id] = task_id

    def task_id_for_message(self, message_id: str) -> str | None:
        return self._message_ids.get(message_id)

    def claim_message_id(self, message_id: str) -> tuple[bool, str | None]:
        """Atomically check-and-claim a message_id.

        Returns (True, None) if the caller is the first to claim message_id
        and must now create+register a task for it. Returns (False, existing)
        if someone already claimed it -- existing is the task_id if that
        earlier caller already registered one, or None if it's still pending.
        Safe without a lock because callers only reach this from an `async
        def` handler with no `await` between their check and this call, so
        the event loop never switches to another request mid-check.
        """
        if message_id in self._message_ids:
            return False, self._message_ids[message_id]
        self._message_ids[message_id] = None
        return True, None

    def release_message_id(self, message_id: str) -> None:
        self._message_ids.pop(message_id, None)
