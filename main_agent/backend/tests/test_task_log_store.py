from datetime import datetime, timezone

from app.task_log_store import TaskLogStore


def test_task_log_store_appends_and_filters_logs_by_owner_and_day():
    store = TaskLogStore(":memory:")
    store.append(
        agent="Game Q&A",
        task_name="스토리 검토",
        owner="김담당",
        status="진행 중",
        result_summary="1장 검토 중",
        recorded_at=datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc),
        reset_id="reset-1",
    )
    store.append(
        agent="Video Generation",
        task_name="영상 생성",
        owner="이담당",
        status="완료",
        result_summary="초안 생성 완료",
        recorded_at=datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc),
        reset_id="reset-1",
    )

    logs = store.list_logs(work_date="2026-08-18", owner="김담당")

    assert len(logs) == 1
    assert logs[0]["agent"] == "Game Q&A"
    assert logs[0]["owner"] == "김담당"


def test_task_log_store_reset_creates_a_new_append_only_segment():
    store = TaskLogStore(":memory:")
    first = store.reset(work_date="2026-08-18", reset_at=datetime(2026, 8, 18, 12, 30, tzinfo=timezone.utc))
    second = store.reset(work_date="2026-08-18", reset_at=datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc))
    store.append(
        agent="Workmate AI",
        task_name="브리핑",
        owner="김담당",
        status="완료",
        result_summary="완료",
        recorded_at=datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc),
        reset_id=second["reset_id"],
    )

    assert first["reset_id"] != second["reset_id"]
    assert len(store.list_resets(work_date="2026-08-18")) == 2
    assert len(store.list_logs(work_date="2026-08-18", reset_id=second["reset_id"])) == 1
