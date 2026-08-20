"""Local tracking of Veo API calls, for a "N / limit used today" display.

Google's Developer API (plain API-key auth, which this pipeline uses) has no
endpoint that returns remaining quota - the aistudio.google.com/rate-limit
page is a Google AI Studio console feature tied to a logged-in Google
account, not something callable with just an API key. So instead we count
our own calls locally, the same SQLite-under-.runtime/ pattern as
task_repository.py - fully local, no hosted database.

Caveat (surfaced to the user, not hidden): this only counts calls made
through this app. A call made via scripts/gemini_pipeline_smoke_test.py run
by hand outside Docker shares the same API key/quota but wouldn't be seen
here, so this can undercount relative to Google's real usage.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

USAGE_DB_PATH_ENV = "VIDEO_AGENT_USAGE_DB_PATH"
DAILY_LIMIT_ENV = "VEO_DAILY_QUOTA_LIMIT"
_DEFAULT_DB_PATH = ".runtime/veo_usage.sqlite3"
_DEFAULT_DAILY_LIMIT = 10
_WINDOW_HOURS = 24


class SQLiteVeoUsageRepository:
    """Local-only usage counter - no server-side/hosted database involved."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.database_path = str(database_path)
        self._use_uri = self.database_path == ":memory:"
        # Plain sqlite3.connect(":memory:") gives every connection its own
        # isolated, empty database - a named shared-cache URI is required so
        # repeated _connect() calls (record_call() then count_recent(), etc.)
        # see the same in-memory data.
        self._connection_target = (
            f"file:video-agent-veo-usage-{uuid4().hex}?mode=memory&cache=shared" if self._use_uri else self.database_path
        )
        if not self._use_uri:
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._anchor = sqlite3.connect(self._connection_target, uri=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._connection_target, uri=self._use_uri)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS veo_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, called_at TEXT NOT NULL)"
            )

    def record_call(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO veo_calls(called_at) VALUES (?)", (datetime.now(timezone.utc).isoformat(),)
            )

    def count_recent(self, window_hours: int = _WINDOW_HOURS) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) FROM veo_calls WHERE called_at >= ?", (cutoff,)).fetchone()
        return row[0]

    def oldest_recent_call_at(self, window_hours: int = _WINDOW_HOURS) -> str | None:
        """When the oldest call inside the window happened - that call drops
        out of the window (freeing up one unit) at called_at + window_hours."""

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT MIN(called_at) FROM veo_calls WHERE called_at >= ?", (cutoff,)
            ).fetchone()
        return row[0]


def veo_usage_repository() -> SQLiteVeoUsageRepository:
    """The repository the real running server uses - a local SQLite file
    under .runtime/, volume-mounted so it survives container recreation."""

    return SQLiteVeoUsageRepository(os.getenv(USAGE_DB_PATH_ENV, _DEFAULT_DB_PATH))


def daily_limit() -> int:
    return int(os.getenv(DAILY_LIMIT_ENV, str(_DEFAULT_DAILY_LIMIT)))


__all__ = [
    "SQLiteVeoUsageRepository",
    "veo_usage_repository",
    "daily_limit",
    "USAGE_DB_PATH_ENV",
    "DAILY_LIMIT_ENV",
]
