import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class SessionMemory:
    def __init__(self, database_url: str):
        self._engine: Engine = create_engine(database_url, pool_pre_ping=True)
        self._init_schema()

    def _execute(self, sql: str, **params) -> Any:
        with self._engine.connect() as conn:
            result = conn.execute(text(sql), params)
            conn.commit()
            return result

    def _fetchone(self, sql: str, **params) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
            return dict(row) if row else None

    def _fetchall(self, sql: str, **params) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            return [dict(r) for r in rows]

    def _init_schema(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(text("""
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
                )
            """))
            conn.execute(text("""
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
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    finding_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT,
                    severity TEXT DEFAULT 'medium'
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    request_id TEXT NOT NULL,
                    stream TEXT NOT NULL,
                    data TEXT NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS session_threads (
                    thread_id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agents (
                    user_id TEXT PRIMARY KEY,
                    ws_url TEXT NOT NULL,
                    token TEXT NOT NULL,
                    label TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """))
            conn.commit()

    def _is_sqlite(self) -> bool:
        return "sqlite" in self._engine.url.drivername

    def _next_id(self) -> int:
        if self._is_sqlite():
            return 0
        return int(time.time() * 1000)

    # ── Agent methods ──

    async def save_agent(self, user_id: str, ws_url: str, token: str, label: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = await self.get_agent(user_id)
        if existing:
            self._execute(
                "UPDATE agents SET ws_url = :ws_url, token = :token, label = :label, updated_at = :now WHERE user_id = :user_id",
                user_id=user_id, ws_url=ws_url, token=token, label=label, now=now,
            )
        else:
            self._execute(
                "INSERT INTO agents (user_id, ws_url, token, label, created_at, updated_at) VALUES (:user_id, :ws_url, :token, :label, :now, :now)",
                user_id=user_id, ws_url=ws_url, token=token, label=label, now=now,
            )

    async def get_agent(self, user_id: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM agents WHERE user_id = :user_id", user_id=user_id)

    async def delete_agent(self, user_id: str) -> None:
        self._execute("DELETE FROM agents WHERE user_id = :user_id", user_id=user_id)

    async def list_agents(self) -> list[dict]:
        return self._fetchall("SELECT * FROM agents ORDER BY created_at DESC")

    # ── Session methods ──

    async def get_or_create_session(self, user_id: str, session_id: Optional[str] = None) -> str:
        if session_id:
            return session_id
        sid = str(user_id)
        existing = self._fetchone("SELECT id FROM sessions WHERE id = :sid", sid=sid)
        if not existing:
            now = datetime.now(timezone.utc).isoformat()
            self._execute(
                "INSERT INTO sessions (id, user_id, started_at, status) VALUES (:sid, :user_id, :now, 'active')",
                sid=sid, user_id=user_id, now=now,
            )
        return sid

    async def update_session(self, session_id: str, **kwargs) -> None:
        allowed = {"dc_host", "domain", "username", "password", "target_notes", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k} = :{k}" for k in updates)
        params = {**updates, "session_id": session_id}
        self._execute(f"UPDATE sessions SET {sets} WHERE id = :session_id", **params)

    async def log_command(
        self, session_id: str, user_id: str, command: str,
        exit_code: int = 0, output_summary: str = "",
        duration_ms: int = 0, tags: list[str] = None, agent_name: str = "",
    ) -> None:
        self._execute(
            "INSERT INTO commands (session_id, user_id, timestamp, command, exit_code, output_summary, tags, duration_ms, agent_name) "
            "VALUES (:session_id, :user_id, :ts, :command, :exit_code, :summary, :tags, :duration_ms, :agent_name)",
            session_id=session_id, user_id=user_id, ts=datetime.now(timezone.utc).isoformat(),
            command=command, exit_code=exit_code, summary=(output_summary or "")[:500],
            tags=json.dumps(tags or []), duration_ms=duration_ms, agent_name=agent_name,
        )

    async def log_finding(
        self, session_id: str, finding_type: str, title: str,
        detail: dict[str, Any], severity: str = "medium",
    ) -> None:
        self._execute(
            "INSERT INTO findings (session_id, timestamp, finding_type, title, detail, severity) "
            "VALUES (:session_id, :ts, :type, :title, :detail, :severity)",
            session_id=session_id, ts=datetime.now(timezone.utc).isoformat(),
            type=finding_type, title=title, detail=json.dumps(detail), severity=severity,
        )

    async def get_session_context(self, session_id: str) -> dict[str, Any]:
        session_row = self._fetchone("SELECT * FROM sessions WHERE id = :sid", sid=session_id)
        command_rows = self._fetchall(
            "SELECT command, exit_code, output_summary, tags FROM commands WHERE session_id = :sid ORDER BY id DESC LIMIT 20",
            sid=session_id,
        )
        finding_rows = self._fetchall(
            "SELECT finding_type, title, severity, detail FROM findings WHERE session_id = :sid ORDER BY id DESC",
            sid=session_id,
        )
        return {
            "session": session_row,
            "recent_commands": [
                {"command": r["command"], "exit_code": r["exit_code"],
                 "summary": r["output_summary"], "tags": json.loads(r["tags"]) if r["tags"] else []}
                for r in command_rows
            ],
            "findings": [
                {"type": r["finding_type"], "title": r["title"],
                 "severity": r["severity"], "detail": json.loads(r["detail"]) if r["detail"] else {}}
                for r in finding_rows
            ],
        }

    async def add_chat_message(self, session_id: str, role: str, content: str) -> None:
        self._execute(
            "INSERT INTO chat_history (session_id, role, content, timestamp) VALUES (:sid, :role, :content, :ts)",
            sid=session_id, role=role, content=content, ts=datetime.now(timezone.utc).isoformat(),
        )

    async def get_chat_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        rows = self._fetchall(
            "SELECT role, content FROM chat_history WHERE session_id = :sid ORDER BY id DESC LIMIT :lim",
            sid=session_id, lim=limit,
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def log_event(self, event_type: str, data: str) -> None:
        self._execute(
            "INSERT INTO events (ts, type, data) VALUES (:ts, :type, :data)",
            ts=int(time.time()), type=event_type, data=data,
        )

    async def log_output(self, request_id: str, stream: str, data: str) -> None:
        self._execute(
            "INSERT INTO outputs (ts, request_id, stream, data) VALUES (:ts, :rid, :stream, :data)",
            ts=int(time.time()), rid=request_id, stream=stream, data=data,
        )

    async def get_recent_events(self, limit: int = 20) -> list:
        return self._fetchall(
            "SELECT ts, type, data FROM events ORDER BY id DESC LIMIT :lim", lim=limit,
        )

    async def register_thread(self, thread_id: int, session_id: str, guild_id: int, channel_id: int) -> None:
        existing = self._fetchone("SELECT thread_id FROM session_threads WHERE thread_id = :tid", tid=thread_id)
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            self._execute(
                "UPDATE session_threads SET session_id = :sid, guild_id = :gid, channel_id = :cid, created_at = :ts WHERE thread_id = :tid",
                tid=thread_id, sid=session_id, gid=guild_id, cid=channel_id, ts=now,
            )
        else:
            self._execute(
                "INSERT INTO session_threads (thread_id, session_id, guild_id, channel_id, created_at) VALUES (:tid, :sid, :gid, :cid, :ts)",
                tid=thread_id, sid=session_id, gid=guild_id, cid=channel_id, ts=now,
            )

    async def get_session_by_thread(self, thread_id: int) -> Optional[dict]:
        return self._fetchone("SELECT * FROM session_threads WHERE thread_id = :tid", tid=thread_id)

    async def get_thread_by_session(self, session_id: str) -> Optional[int]:
        row = self._fetchone("SELECT thread_id FROM session_threads WHERE session_id = :sid", sid=session_id)
        return row["thread_id"] if row else None

    async def remove_thread_mapping(self, thread_id: int) -> None:
        self._execute("DELETE FROM session_threads WHERE thread_id = :tid", tid=thread_id)

    def close(self) -> None:
        self._engine.dispose()
