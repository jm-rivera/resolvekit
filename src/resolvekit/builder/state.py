"""SQLite-backed run state store for resumable builds."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

from resolvekit.builder.utils import utc_now_iso


class RunStateStore:
    """Persistent state for a build run."""

    SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS stages (
            stage TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            entity_ids_json TEXT NOT NULL,
            status TEXT NOT NULL,
            failed_stage TEXT,
            extract_attempts INTEGER NOT NULL DEFAULT 0,
            normalize_attempts INTEGER NOT NULL DEFAULT 0,
            materialize_attempts INTEGER NOT NULL DEFAULT 0,
            raw_path TEXT,
            normalized_path TEXT,
            materialized INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_status ON chunks(status, domain);
        CREATE INDEX IF NOT EXISTS idx_chunks_failed_stage ON chunks(failed_stage, domain);

        CREATE TABLE IF NOT EXISTS run_meta (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
    """

    _STAGE_ATTEMPT_COLUMN: ClassVar[dict[str, str]] = {
        "extract": "extract_attempts",
        "normalize": "normalize_attempts",
        "materialize": "materialize_attempts",
    }
    _SUCCESS_STAGE_STATUS: ClassVar[dict[str, str]] = {
        "extract": "extracted",
        "normalize": "normalized",
        "materialize": "materialized",
    }

    _CHUNK_STAGE_WHERE: ClassVar[dict[str, str]] = {
        "extract": """
            (status = 'pending')
            OR (
              status = 'failed'
              AND failed_stage = 'extract'
              AND extract_attempts < ?
            )
        """,
        "normalize": """
            (status = 'extracted')
            OR (
              status = 'failed'
              AND failed_stage = 'normalize'
              AND normalize_attempts < ?
            )
        """,
        "materialize": """
            (
              status = 'normalized'
              AND materialized = 0
            )
            OR (
              status = 'failed'
              AND failed_stage = 'materialize'
              AND materialize_attempts < ?
            )
        """,
    }

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(self.SCHEMA_SQL)

    @contextmanager
    def _connect(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        if read_only:
            conn = self._open_connection(write=False)
            try:
                yield conn
            finally:
                conn.close()
            return

        with self._write_lock:
            conn = self._open_connection(write=True)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _open_connection(self, *, write: bool) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        if write:
            conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def initialize_stages(self, stages: list[str]) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO stages(stage, status, updated_at)
                VALUES (?, 'pending', ?)
                """,
                [(stage, now) for stage in stages],
            )

    def get_stage_status(self, stage: str) -> str:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT status FROM stages WHERE stage = ?", (stage,)
            ).fetchone()
            if row is None:
                return "pending"
            return str(row["status"])

    def get_all_stage_statuses(self) -> dict[str, str]:
        with self._connect(read_only=True) as conn:
            rows = conn.execute("SELECT stage, status FROM stages").fetchall()
            return {str(row["stage"]): str(row["status"]) for row in rows}

    def set_stage_status(self, stage: str, status: str) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stages(stage, status, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(stage) DO UPDATE SET
                  status=excluded.status,
                  updated_at=excluded.updated_at
                """,
                (stage, status, now),
            )

    def set_meta(self, key: str, value: Any) -> None:
        payload = json.dumps(value)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_meta(key, value_json)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json
                """,
                (key, payload),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT value_json FROM run_meta WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return default
            return json.loads(str(row["value_json"]))

    def upsert_chunk(self, chunk_id: str, domain: str, entity_ids: list[str]) -> None:
        now = utc_now_iso()
        payload = json.dumps(entity_ids)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chunks(
                    chunk_id, domain, entity_ids_json, status, updated_at
                ) VALUES (?, ?, ?, 'pending', ?)
                ON CONFLICT(chunk_id) DO NOTHING
                """,
                (chunk_id, domain, payload, now),
            )

    def delete_chunks_for_domain(self, domain: str) -> None:
        """Remove chunk inventory for one domain before rediscovery."""
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE domain = ?", (domain,))

    def list_chunks(self, domain: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM chunks"
        params: tuple[Any, ...] = ()
        if domain:
            query += " WHERE domain = ?"
            params = (domain,)
        query += " ORDER BY domain, chunk_id"
        with self._connect(read_only=True) as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def domains(self) -> list[str]:
        """Return discovered chunk domains in stable order."""
        with self._connect(read_only=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT domain FROM chunks ORDER BY domain"
            ).fetchall()
            return [str(row["domain"]) for row in rows]

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Chunk not found: {chunk_id}")
            return dict(row)

    def chunks_for_stage(self, stage: str, max_retries: int) -> list[dict[str, Any]]:
        where_clause = self._CHUNK_STAGE_WHERE.get(stage)
        if where_clause is None:
            raise ValueError(f"Unsupported stage: {stage}")

        with self._connect(read_only=True) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM chunks
                WHERE
                  {where_clause}
                ORDER BY domain, chunk_id
                """,
                (max_retries,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_chunk_success(
        self,
        *,
        chunk_id: str,
        stage: str,
        raw_path: str | None = None,
        normalized_path: str | None = None,
    ) -> None:
        """Mark one chunk as successfully completed for a stage."""
        status = self._SUCCESS_STAGE_STATUS.get(stage)
        if status is None:
            raise ValueError(f"Unsupported success stage: {stage}")

        now = utc_now_iso()
        stage_payload: dict[str, Any] = {}
        if stage == "extract":
            if not raw_path:
                raise ValueError("raw_path is required for extract success.")
            stage_payload["raw_path"] = raw_path
        elif stage == "normalize":
            if not normalized_path:
                raise ValueError("normalized_path is required for normalize success.")
            stage_payload["normalized_path"] = normalized_path
        else:  # materialize
            stage_payload["materialized"] = 1

        updates: dict[str, Any] = {
            "status": status,
            "failed_stage": None,
            "error": None,
            "updated_at": now,
            **stage_payload,
        }
        set_clause = ", ".join(f"{column}=?" for column in updates)
        values = [updates[column] for column in updates]

        with self._connect() as conn:
            conn.execute(
                f"UPDATE chunks SET {set_clause} WHERE chunk_id=?",
                (*values, chunk_id),
            )

    def mark_chunk_failure(self, *, chunk_id: str, stage: str, error: str) -> None:
        """Mark one chunk as failed for a given stage and increment attempts."""
        self._mark_chunk_failure(chunk_id=chunk_id, stage=stage, error=error)

    def _mark_chunk_failure(self, *, chunk_id: str, stage: str, error: str) -> None:
        attempt_column = self._STAGE_ATTEMPT_COLUMN.get(stage)
        if attempt_column is None:
            raise ValueError(f"Unsupported stage: {stage}")

        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE chunks
                SET status='failed',
                    failed_stage=?,
                    {attempt_column}={attempt_column} + 1,
                    error=?,
                    updated_at=?
                WHERE chunk_id=?
                """,
                (stage, error, now, chunk_id),
            )

    def entity_ids_for_chunk(self, chunk_id: str) -> list[str]:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT entity_ids_json FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Chunk not found: {chunk_id}")
            payload = json.loads(str(row["entity_ids_json"]))
            if not isinstance(payload, list):
                raise ValueError(f"Invalid chunk payload for {chunk_id}")
            return [str(item) for item in payload]

    def has_blocking_failures(self, stage: str, max_retries: int) -> bool:
        attempt_column = self._STAGE_ATTEMPT_COLUMN.get(stage)
        if attempt_column is None:
            raise ValueError(f"Unsupported stage: {stage}")

        with self._connect(read_only=True) as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM chunks
                WHERE status='failed'
                  AND failed_stage=?
                  AND {attempt_column} >= ?
                """,
                (stage, max_retries),
            ).fetchone()
            return int(row["c"]) > 0

    def count_chunks_by_domain(self) -> dict[str, int]:
        with self._connect(read_only=True) as conn:
            rows = conn.execute(
                "SELECT domain, COUNT(*) AS c FROM chunks GROUP BY domain"
            ).fetchall()
            return {str(row["domain"]): int(row["c"]) for row in rows}

    def chunk_counts(self) -> dict[str, int]:
        with self._connect(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS c
                FROM chunks
                GROUP BY status
                """
            ).fetchall()
            return {str(row["status"]): int(row["c"]) for row in rows}
