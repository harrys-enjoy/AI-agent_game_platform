from app.task_store import TaskStore
from app.contracts import TaskEvent


def test_task_store_creates_and_updates_task():
    store = TaskStore(":memory:")
    task = store.create("브리핑해줘", ["workmate-agent"])
    updated = store.update(task.task_id, status="succeeded", result={"ok": True})

    assert updated.status == "succeeded"
    assert updated.result == {"ok": True}


def test_task_store_appends_events():
    store = TaskStore(":memory:")
    task = store.create("브리핑해줘", ["workmate-agent"])
    updated = store.append_event(task.task_id, TaskEvent(type="progress", message="Agent 호출"))

    assert updated.events[-1].message == "Agent 호출"
