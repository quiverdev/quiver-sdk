"""
SQLite-backed session and message store for QuiverCore.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from quiver_sdk.types import AgentMessage, SessionRecord


class SqliteStore:
    """
    Persistent session and message store backed by SQLite.

    Thread-safe via a per-connection lock pattern.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,  # autocommit
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                created_at   INTEGER NOT NULL,
                updated_at   INTEGER NOT NULL,
                status       TEXT NOT NULL DEFAULT 'idle',
                config       TEXT,
                metadata     TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     TEXT NOT NULL,
                message_id     TEXT NOT NULL,
                role           TEXT NOT NULL,
                content        TEXT NOT NULL,
                created_at     INTEGER NOT NULL,
                metadata       TEXT,
                model_info     TEXT,
                metrics        TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at);
        """)

    # ---------- Sessions ----------

    def create_session(
        self,
        session_id: str,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionRecord:
        now = int(time.time() * 1000)
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO sessions (session_id, created_at, updated_at, status, config, metadata)
            VALUES (?, ?, ?, 'idle', ?, ?)
            """,
            (
                session_id,
                now,
                now,
                json.dumps(config) if config else None,
                json.dumps(metadata) if metadata else None,
            ),
        )
        return SessionRecord(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            status="idle",
            config=config,
            metadata=metadata,
        )

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def update_session(
        self,
        session_id: str,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn = self._get_conn()
        now = int(time.time() * 1000)
        parts = ["updated_at = ?"]
        params: List[Any] = [now]
        if status is not None:
            parts.append("status = ?")
            params.append(status)
        if metadata is not None:
            parts.append("metadata = ?")
            params.append(json.dumps(metadata))
        if config is not None:
            parts.append("config = ?")
            params.append(json.dumps(config))
        params.append(session_id)
        conn.execute(
            f"UPDATE sessions SET {', '.join(parts)} WHERE session_id = ?",
            params,
        )

    def delete_session(self, session_id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def list_sessions(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> List[SessionRecord]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def _row_to_session(self, row: sqlite3.Row) -> SessionRecord:
        config = json.loads(row["config"]) if row["config"] else None
        metadata = json.loads(row["metadata"]) if row["metadata"] else None
        return SessionRecord(
            session_id=row["session_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=row["status"],
            config=config,
            metadata=metadata,
        )

    # ---------- Messages ----------

    def append_message(self, session_id: str, message: AgentMessage) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO messages
              (session_id, message_id, role, content, created_at, metadata, model_info, metrics)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                message.id,
                message.role,
                json.dumps(message.content),
                message.created_at,
                json.dumps(message.metadata) if message.metadata else None,
                json.dumps(message.model_info) if message.model_info else None,
                json.dumps(message.metrics) if message.metrics else None,
            ),
        )
        # bump session updated_at
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (int(time.time() * 1000), session_id),
        )

    def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
        after_id: Optional[str] = None,
    ) -> List[AgentMessage]:
        conn = self._get_conn()
        if after_id:
            ref_row = conn.execute(
                "SELECT created_at FROM messages WHERE session_id = ? AND message_id = ?",
                (session_id, after_id),
            ).fetchone()
            if ref_row:
                q = "SELECT * FROM messages WHERE session_id = ? AND created_at > ? ORDER BY created_at ASC"
                params = [session_id, ref_row["created_at"]]
                if limit:
                    q += " LIMIT ?"
                    params.append(limit)
                rows = conn.execute(q, params).fetchall()
                return [self._row_to_message(r) for r in rows]

        q = "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC"
        params = [session_id]
        if limit:
            q += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        rows = conn.execute(q, params).fetchall()
        return [self._row_to_message(r) for r in rows]

    def delete_messages(self, session_id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))

    def get_message_count(self, session_id: str) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["cnt"] if row else 0

    def _row_to_message(self, row: sqlite3.Row) -> AgentMessage:
        content = json.loads(row["content"])
        metadata = json.loads(row["metadata"]) if row["metadata"] else None
        model_info = json.loads(row["model_info"]) if row["model_info"] else None
        metrics = json.loads(row["metrics"]) if row["metrics"] else None
        return AgentMessage(
            id=row["message_id"],
            role=row["role"],
            content=content,
            created_at=row["created_at"],
            metadata=metadata,
            model_info=model_info,
            metrics=metrics,
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()
