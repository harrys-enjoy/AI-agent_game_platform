import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    def __init__(self, path: str = "main_agent.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL UNIQUE,
                current_session_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                session_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            )"""
        )
        conversation_columns = {row[1] for row in self.db.execute("PRAGMA table_info(conversations)")}
        if "current_session_id" not in conversation_columns:
            self.db.execute("ALTER TABLE conversations ADD COLUMN current_session_id TEXT")
        message_columns = {row[1] for row in self.db.execute("PRAGMA table_info(messages)")}
        if "session_id" not in message_columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN session_id TEXT")
        if "metadata" not in message_columns:
            # `assistant_ask`(workmate-agent)가 확인이 필요한 동작을 골랐을 때 돌려주는
            # `pending_action`을 메시지와 함께 저장한다 — 안 그러면 탭 전환·새로고침으로
            # 대화가 이 평문 이력에서 다시 만들어질 때 확인/취소 버튼이 사라진다(2026-08-19
            # 실사용 중 발견). 기존 행은 전부 NULL로 남아 이전 메시지는 그냥 평문으로 남는다
            # — 하위 호환(기존 소비처가 이미 읽는 필드는 그대로 둔다).
            self.db.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        for conversation_id, session_id in self.db.execute("SELECT id, current_session_id FROM conversations").fetchall():
            active_session = session_id or str(uuid.uuid4())
            self.db.execute("UPDATE conversations SET current_session_id=? WHERE id=?", (active_session, conversation_id))
            self.db.execute("UPDATE messages SET session_id=? WHERE conversation_id=? AND session_id IS NULL", (active_session, conversation_id))
        self.db.commit()

    def _conversation(self, agent_name: str) -> tuple[str, str]:
        row = self.db.execute("SELECT id, current_session_id FROM conversations WHERE agent_name=?", (agent_name,)).fetchone()
        if row:
            return row[0], row[1]
        conversation_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        now = utc_now()
        self.db.execute(
            "INSERT INTO conversations(id,agent_name,current_session_id,created_at,updated_at) VALUES (?,?,?,?,?)",
            (conversation_id, agent_name, session_id, now, now),
        )
        self.db.commit()
        return conversation_id, session_id

    def append(
        self, agent_name: str, role: str, content: str, session_id: str | None = None, pending_action: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        conversation_id, current_session_id = self._conversation(agent_name)
        session_id = session_id or current_session_id
        metadata_json = json.dumps({"pending_action": pending_action}, ensure_ascii=False) if pending_action else None
        message = {
            "id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": utc_now(),
            "pending_action": pending_action,
        }
        self.db.execute(
            "INSERT INTO messages(id,conversation_id,session_id,role,content,created_at,metadata) VALUES (?,?,?,?,?,?,?)",
            (message["id"], conversation_id, session_id, role, content, message["created_at"], metadata_json),
        )
        self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (message["created_at"], conversation_id))
        self.db.commit()
        return message

    def list_messages(self, agent_name: str, session_id: str | None = None) -> list[dict[str, Any]]:
        conversation_id, current_session_id = self._conversation(agent_name)
        session_id = session_id or current_session_id
        rows = self.db.execute(
            "SELECT id, conversation_id, session_id, role, content, created_at, metadata FROM messages WHERE conversation_id=? AND session_id=? ORDER BY created_at, rowid",
            (conversation_id, session_id),
        ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            metadata_json = row[6]
            pending_action = None
            if metadata_json:
                try:
                    pending_action = json.loads(metadata_json).get("pending_action")
                except (json.JSONDecodeError, AttributeError):
                    pending_action = None
            messages.append({"id": row[0], "conversation_id": row[1], "session_id": row[2], "role": row[3], "content": row[4], "created_at": row[5], "pending_action": pending_action})
        return messages

    def current_session(self, agent_name: str) -> str:
        return self._conversation(agent_name)[1]

    def reset(self, agent_name: str) -> str:
        conversation_id, _ = self._conversation(agent_name)
        session_id = str(uuid.uuid4())
        self.db.execute("UPDATE conversations SET current_session_id=?, updated_at=? WHERE id=?", (session_id, utc_now(), conversation_id))
        self.db.commit()
        return session_id
