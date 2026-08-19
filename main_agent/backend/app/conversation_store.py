import sqlite3
import uuid
from datetime import datetime, timezone


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
            """CREATE TABLE IF NOT EXISTS assignee_conversations (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                owner TEXT NOT NULL,
                current_session_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(agent_name, owner)
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
        for conversation_id, session_id in self.db.execute("SELECT id, current_session_id FROM conversations").fetchall():
            active_session = session_id or str(uuid.uuid4())
            self.db.execute("UPDATE conversations SET current_session_id=? WHERE id=?", (active_session, conversation_id))
            self.db.execute("UPDATE messages SET session_id=? WHERE conversation_id=? AND session_id IS NULL", (active_session, conversation_id))
        self.db.execute(
            """INSERT OR IGNORE INTO assignee_conversations(id, agent_name, owner, current_session_id, created_at, updated_at)
               SELECT id, agent_name, 'default', current_session_id, created_at, updated_at FROM conversations"""
        )
        self.db.commit()

    def _conversation(self, agent_name: str, owner: str = "default") -> tuple[str, str]:
        owner = owner or "default"
        row = self.db.execute("SELECT id, current_session_id FROM assignee_conversations WHERE agent_name=? AND owner=?", (agent_name, owner)).fetchone()
        if row:
            return row[0], row[1]
        conversation_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        now = utc_now()
        self.db.execute(
            "INSERT INTO assignee_conversations(id,agent_name,owner,current_session_id,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (conversation_id, agent_name, owner, session_id, now, now),
        )
        self.db.commit()
        return conversation_id, session_id

    def append(self, agent_name: str, role: str, content: str, session_id: str | None = None, owner: str = "default") -> dict[str, str]:
        conversation_id, current_session_id = self._conversation(agent_name, owner)
        session_id = session_id or current_session_id
        message = {"id": str(uuid.uuid4()), "conversation_id": conversation_id, "session_id": session_id, "role": role, "content": content, "created_at": utc_now()}
        self.db.execute(
            "INSERT INTO messages(id,conversation_id,session_id,role,content,created_at) VALUES (?,?,?,?,?,?)",
            (message["id"], conversation_id, session_id, role, content, message["created_at"]),
        )
        self.db.execute("UPDATE assignee_conversations SET updated_at=? WHERE id=?", (message["created_at"], conversation_id))
        self.db.commit()
        return message

    def list_messages(self, agent_name: str, session_id: str | None = None, owner: str = "default") -> list[dict[str, str]]:
        conversation_id, current_session_id = self._conversation(agent_name, owner)
        session_id = session_id or current_session_id
        rows = self.db.execute(
            "SELECT id, conversation_id, session_id, role, content, created_at FROM messages WHERE conversation_id=? AND session_id=? ORDER BY created_at, rowid",
            (conversation_id, session_id),
        ).fetchall()
        return [{"id": row[0], "conversation_id": row[1], "session_id": row[2], "role": row[3], "content": row[4], "created_at": row[5]} for row in rows]

    def current_session(self, agent_name: str, owner: str = "default") -> str:
        return self._conversation(agent_name, owner)[1]

    def reset(self, agent_name: str, owner: str = "default") -> str:
        conversation_id, _ = self._conversation(agent_name, owner)
        session_id = str(uuid.uuid4())
        self.db.execute("UPDATE assignee_conversations SET current_session_id=?, updated_at=? WHERE id=?", (session_id, utc_now(), conversation_id))
        self.db.commit()
        return session_id
