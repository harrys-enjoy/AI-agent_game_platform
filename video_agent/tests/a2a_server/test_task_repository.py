from video_draft_pipeline.a2a_server.task_repository import SQLiteTaskRepository
from video_draft_pipeline.a2a_server.tasks import TaskRecord


def test_save_and_load_all_round_trips_with_default_in_memory_database():
    """Regression: plain sqlite3.connect(":memory:") gives every connection
    its own isolated, empty database, so save() (one connection) followed by
    load_all() (a separate connection) previously always saw an empty table
    - "no such table: tasks" in the worst case. Needs the shared-cache URI."""

    repo = SQLiteTaskRepository()
    repo.save(TaskRecord(task_id="t1", user_id="u1", brief="테스트"))

    loaded = repo.load_all()

    assert len(loaded) == 1
    assert loaded[0].task_id == "t1"
    assert loaded[0].brief == "테스트"


def test_two_default_instances_do_not_share_state():
    """Each SQLiteTaskRepository() gets its own uniquely-named shared-cache
    URI, so two separate instances (e.g. two unrelated tests) must not see
    each other's data."""

    first = SQLiteTaskRepository()
    second = SQLiteTaskRepository()
    first.save(TaskRecord(task_id="only-in-first"))

    assert second.load_all() == []


def test_survives_recreation_against_the_same_file(tmp_path):
    db_path = tmp_path / "tasks.sqlite3"
    first = SQLiteTaskRepository(db_path)
    first.save(TaskRecord(task_id="t1", user_id="u1"))

    second = SQLiteTaskRepository(db_path)

    assert [record.task_id for record in second.load_all()] == ["t1"]


def test_list_for_user_filters_and_paginates():
    repo = SQLiteTaskRepository()
    repo.save(TaskRecord(task_id="a", user_id="u1"))
    repo.save(TaskRecord(task_id="b", user_id="u2"))
    repo.save(TaskRecord(task_id="c", user_id="u1"))

    records, has_more = repo.list_for_user("u1", limit=10, offset=0)

    assert {record.task_id for record in records} == {"a", "c"}
    assert has_more is False


def test_delete_removes_the_row():
    repo = SQLiteTaskRepository()
    repo.save(TaskRecord(task_id="t1"))

    repo.delete("t1")

    assert repo.load_all() == []
