import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Optional


class SessionMemory:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                dc_host TEXT,
                domain TEXT,
                username TEXT,
                password TEXT,
                target_notes TEXT,
                status TEXT DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                command TEXT NOT NULL,
                exit_code INTEGER,
                output_summary TEXT,
                full_output_path TEXT,
                tags TEXT,
                duration_ms INTEGER,
                agent_name TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                finding_type TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT,
                severity TEXT DEFAULT 'medium'
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                request_id TEXT NOT NULL,
                stream TEXT NOT NULL,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS session_threads (
                thread_id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
        """)
        self.conn.commit()

    async def get_or_create_session(self, user_id: str, session_id: Optional[str] = None) -> str:
        if session_id:
            return session_id
        sid = str(user_id)
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM sessions WHERE id=?", (sid,))
        row = cur.fetchone()
        if not row:
            now = datetime.now(timezone.utc).isoformat()
            cur.execute(
                "INSERT INTO sessions (id, user_id, started_at, status) VALUES (?, ?, ?, 'active')",
                (sid, user_id, now),
            )
            self.conn.commit()
        return sid

    async def update_session(self, session_id: str, **kwargs) -> None:
        allowed = {"dc_host", "domain", "username", "password", "target_notes", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [session_id]
        cur = self.conn.cursor()
        cur.execute(f"UPDATE sessions SET {sets} WHERE id=?", vals)
        self.conn.commit()

    async def log_command(
        self,
        session_id: str,
        user_id: str,
        command: str,
        exit_code: int = 0,
        output_summary: str = "",
        duration_ms: int = 0,
        tags: list[str] = None,
        agent_name: str = "",
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO commands
               (session_id, user_id, timestamp, command, exit_code, output_summary, tags, duration_ms, agent_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                user_id,
                datetime.now(timezone.utc).isoformat(),
                command,
                exit_code,
                output_summary[:500],
                json.dumps(tags or []),
                duration_ms,
                agent_name,
            ),
        )
        self.conn.commit()

    async def log_finding(
        self,
        session_id: str,
        finding_type: str,
        title: str,
        detail: dict[str, Any],
        severity: str = "medium",
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO findings (session_id, timestamp, finding_type, title, detail, severity)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                datetime.now(timezone.utc).isoformat(),
                finding_type,
                title,
                json.dumps(detail),
                severity,
            ),
        )
        self.conn.commit()

    async def get_session_context(self, session_id: str) -> dict[str, Any]:
        cur = self.conn.cursor()

        cur.execute(
            "SELECT * FROM sessions WHERE id=?",
            (session_id,),
        )
        session_row = cur.fetchone()

        cur.execute(
            "SELECT command, exit_code, output_summary, tags FROM commands WHERE session_id=? ORDER BY id DESC LIMIT 20",
            (session_id,),
        )
        command_rows = cur.fetchall()

        cur.execute(
            "SELECT finding_type, title, severity, detail FROM findings WHERE session_id=? ORDER BY id DESC",
            (session_id,),
        )
        finding_rows = cur.fetchall()

        return {
            "session": dict(session_row) if session_row else None,
            "recent_commands": [
                {
                    "command": r["command"],
                    "exit_code": r["exit_code"],
                    "summary": r["output_summary"],
                    "tags": json.loads(r["tags"]) if r["tags"] else [],
                }
                for r in command_rows
            ],
            "findings": [
                {
                    "type": r["finding_type"],
                    "title": r["title"],
                    "severity": r["severity"],
                    "detail": json.loads(r["detail"]) if r["detail"] else {},
                }
                for r in finding_rows
            ],
        }

    async def add_chat_message(self, session_id: str, role: str, content: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO chat_history (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    async def get_chat_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT role, content FROM chat_history WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        rows = cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def log_event(self, event_type: str, data: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO events (ts, type, data) VALUES (?, ?, ?)",
            (int(time.time()), event_type, data),
        )
        self.conn.commit()

    async def log_output(self, request_id: str, stream: str, data: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO outputs (ts, request_id, stream, data) VALUES (?, ?, ?, ?)",
            (int(time.time()), request_id, stream, data),
        )
        self.conn.commit()

    async def get_recent_events(self, limit: int = 20) -> list:
        cur = self.conn.cursor()
        cur.execute("SELECT ts, type, data FROM events ORDER BY id DESC LIMIT ?", (limit,))
        return cur.fetchall()

    async def register_thread(self, thread_id: int, session_id: str, guild_id: int, channel_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO session_threads (thread_id, session_id, guild_id, channel_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (thread_id, session_id, guild_id, channel_id, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    async def get_session_by_thread(self, thread_id: int) -> Optional[dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM session_threads WHERE thread_id=?", (thread_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    async def get_thread_by_session(self, session_id: str) -> Optional[int]:
        cur = self.conn.cursor()
        cur.execute("SELECT thread_id FROM session_threads WHERE session_id=?", (session_id,))
        row = cur.fetchone()
        return row["thread_id"] if row else None

    async def remove_thread_mapping(self, thread_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM session_threads WHERE thread_id=?", (thread_id,))
        self.conn.commit()
