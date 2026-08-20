from datetime import datetime, timedelta, timezone

from video_draft_pipeline.a2a_server.veo_usage_repository import SQLiteVeoUsageRepository


def test_count_recent_is_zero_with_no_calls():
    repo = SQLiteVeoUsageRepository()

    assert repo.count_recent() == 0
    assert repo.oldest_recent_call_at() is None


def test_count_recent_counts_calls_within_window():
    repo = SQLiteVeoUsageRepository()

    repo.record_call()
    repo.record_call()
    repo.record_call()

    assert repo.count_recent(window_hours=24) == 3


def test_count_recent_excludes_calls_outside_window():
    repo = SQLiteVeoUsageRepository()
    with repo._connect() as connection:
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        connection.execute("INSERT INTO veo_calls(called_at) VALUES (?)", (old,))
        connection.execute("INSERT INTO veo_calls(called_at) VALUES (?)", (recent,))

    assert repo.count_recent(window_hours=24) == 1


def test_survives_recreation_against_the_same_file(tmp_path):
    """Simulates a container restart - a fresh repository instance pointed
    at the same file must see previously recorded calls."""

    db_path = tmp_path / "veo_usage.sqlite3"
    first = SQLiteVeoUsageRepository(db_path)
    first.record_call()
    first.record_call()

    second = SQLiteVeoUsageRepository(db_path)

    assert second.count_recent() == 2


def test_oldest_recent_call_at_returns_earliest_timestamp_in_window():
    repo = SQLiteVeoUsageRepository()
    repo.record_call()
    first_call_at = repo.oldest_recent_call_at()
    repo.record_call()

    assert repo.oldest_recent_call_at() == first_call_at
