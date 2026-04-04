#!/usr/bin/env python3
"""
Shared Task Store for Hermes Agent team workflows.

Provides a persistent SQLite-backed task board visible and writable by all
agent processes (coder, reviewer, human). Designed for the coder → reviewer
handover workflow: tasks move through a defined status lifecycle, and each
transition can carry handover notes for the next agent.

Key design decisions:
- Separate database file (tasks.db) so task data doesn't pollute session history
- WAL mode + jitter-retry write helper (copied from SessionDB) for concurrent writers
- Strict status transition enforcement — invalid moves return ValueError, not corrupt data
- IDs are short hex strings prefixed with "task_" for readability
- All timestamps stored as Unix floats (same as SessionDB)
"""

import json
import logging
import random
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_DB_PATH = get_hermes_home() / "tasks.db"

SCHEMA_VERSION = 1

VALID_STATUSES = frozenset({
    "pending",
    "in_progress",
    "in_review",
    "needs_revision",
    "completed",
    "cancelled",
})

VALID_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})

# Permitted (from_status → set of allowed to_statuses)
VALID_TRANSITIONS: Dict[str, frozenset] = {
    "pending":        frozenset({"in_progress", "cancelled"}),
    "in_progress":    frozenset({"in_review", "completed", "cancelled"}),
    "in_review":      frozenset({"needs_revision", "completed", "cancelled"}),
    "needs_revision": frozenset({"in_progress", "cancelled"}),
    "completed":      frozenset(),   # terminal
    "cancelled":      frozenset(),   # terminal
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    priority        TEXT NOT NULL DEFAULT 'normal',
    assigned_to     TEXT,
    created_by      TEXT NOT NULL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    branch          TEXT,
    pr_url          TEXT,
    handover_notes  TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_assigned  ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created   ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_updated   ON tasks(updated_at DESC);
"""


def _new_task_id() -> str:
    """Generate a short, human-readable task ID."""
    return "task_" + uuid.uuid4().hex[:10]


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


class SharedTaskDB:
    """
    SQLite-backed shared task board. One file, many writers.

    Thread-safe for multiple concurrent agent processes via WAL mode +
    application-level jitter retry (same pattern as SessionDB).
    """

    # ── Write-contention tuning (same values as SessionDB) ──
    _WRITE_MAX_RETRIES = 15
    _WRITE_RETRY_MIN_S = 0.020   # 20ms
    _WRITE_RETRY_MAX_S = 0.150   # 150ms
    _CHECKPOINT_EVERY_N_WRITES = 50

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._write_count = 0
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=1.0,
            isolation_level=None,   # We manage transactions ourselves
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ── Core write helper (copied from SessionDB) ──

    def _execute_write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Execute a write transaction with BEGIN IMMEDIATE and jitter retry."""
        last_err: Optional[Exception] = None
        for attempt in range(self._WRITE_MAX_RETRIES):
            try:
                with self._lock:
                    self._conn.execute("BEGIN IMMEDIATE")
                    try:
                        result = fn(self._conn)
                        self._conn.commit()
                    except BaseException:
                        try:
                            self._conn.rollback()
                        except Exception:
                            pass
                        raise
                self._write_count += 1
                if self._write_count % self._CHECKPOINT_EVERY_N_WRITES == 0:
                    self._try_wal_checkpoint()
                return result
            except sqlite3.OperationalError as exc:
                err_msg = str(exc).lower()
                if "locked" in err_msg or "busy" in err_msg:
                    last_err = exc
                    if attempt < self._WRITE_MAX_RETRIES - 1:
                        jitter = random.uniform(
                            self._WRITE_RETRY_MIN_S,
                            self._WRITE_RETRY_MAX_S,
                        )
                        time.sleep(jitter)
                        continue
                raise
        raise last_err or sqlite3.OperationalError(
            "database is locked after max retries"
        )

    def _try_wal_checkpoint(self) -> None:
        try:
            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            if self._conn:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except Exception:
                    pass
                self._conn.close()
                self._conn = None

    # ── Schema init ──

    def _init_schema(self) -> None:
        def _setup(conn: sqlite3.Connection) -> None:
            conn.executescript(SCHEMA_SQL)
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
            # Future migrations would check row["version"] < N and ALTER TABLE here.

        self._execute_write(_setup)

    # ── Public API ──

    def create_task(
        self,
        title: str,
        created_by: str,
        description: Optional[str] = None,
        assigned_to: Optional[str] = None,
        priority: str = "normal",
        branch: Optional[str] = None,
        pr_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new task and return it."""
        if not title or not title.strip():
            raise ValueError("title is required")
        if priority not in VALID_PRIORITIES:
            priority = "normal"

        task_id = _new_task_id()
        now = time.time()

        def _insert(conn: sqlite3.Connection) -> None:
            conn.execute(
                """INSERT INTO tasks
                   (id, title, description, status, priority, assigned_to,
                    created_by, created_at, updated_at, branch, pr_url, handover_notes)
                   VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (task_id, title.strip(), description, priority,
                 assigned_to, created_by, now, now, branch, pr_url),
            )

        self._execute_write(_insert)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return a task dict by ID, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def update_task(
        self,
        task_id: str,
        **fields: Any,
    ) -> Dict[str, Any]:
        """
        Update arbitrary fields on a task.

        Validates status transitions. Raises ValueError on invalid transition
        or if the task doesn't exist.

        Updatable fields: title, description, status, priority, assigned_to,
        branch, pr_url, handover_notes.
        """
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id!r} not found")

        allowed_fields = {
            "title", "description", "status", "priority",
            "assigned_to", "branch", "pr_url", "handover_notes",
        }
        updates = {k: v for k, v in fields.items() if k in allowed_fields}
        if not updates:
            return task

        # Validate status transition
        if "status" in updates:
            new_status = updates["status"]
            if new_status not in VALID_STATUSES:
                raise ValueError(
                    f"Invalid status {new_status!r}. "
                    f"Valid values: {sorted(VALID_STATUSES)}"
                )
            current = task["status"]
            if new_status != current:
                allowed = VALID_TRANSITIONS.get(current, frozenset())
                if new_status not in allowed:
                    raise ValueError(
                        f"Cannot transition task from {current!r} to {new_status!r}. "
                        f"Allowed next states: {sorted(allowed) or ['(none — terminal)']}"
                    )

        if "priority" in updates and updates["priority"] not in VALID_PRIORITIES:
            updates["priority"] = "normal"

        now = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [now, task_id]

        def _update(conn: sqlite3.Connection) -> None:
            conn.execute(
                f"UPDATE tasks SET {set_clause}, updated_at = ? WHERE id = ?",
                values,
            )

        self._execute_write(_update)
        return self.get_task(task_id)

    def list_tasks(
        self,
        assigned_to: Optional[str] = None,
        status: Optional[str] = None,
        include_terminal: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List tasks, optionally filtered.

        By default excludes completed/cancelled tasks unless include_terminal=True.
        """
        conditions = []
        params: List[Any] = []

        if assigned_to is not None:
            conditions.append("assigned_to = ?")
            params.append(assigned_to)

        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        elif not include_terminal:
            conditions.append("status NOT IN ('completed', 'cancelled')")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        rows = self._conn.execute(
            f"""SELECT * FROM tasks {where}
                ORDER BY
                  CASE status
                    WHEN 'in_progress'    THEN 1
                    WHEN 'in_review'      THEN 2
                    WHEN 'needs_revision' THEN 3
                    WHEN 'pending'        THEN 4
                    WHEN 'completed'      THEN 5
                    WHEN 'cancelled'      THEN 6
                  END,
                  CASE priority
                    WHEN 'urgent' THEN 1
                    WHEN 'high'   THEN 2
                    WHEN 'normal' THEN 3
                    WHEN 'low'    THEN 4
                  END,
                  updated_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def handover_task(
        self,
        task_id: str,
        from_agent: str,
        to_agent: str,
        handover_notes: str,
        new_status: str = "in_review",
    ) -> Dict[str, Any]:
        """
        Hand a task to another agent.

        Validates that the status transition is legal (e.g. in_progress → in_review).
        Stores handover_notes for the receiving agent to read.
        """
        if not handover_notes or not handover_notes.strip():
            raise ValueError("handover_notes are required for a handover")
        return self.update_task(
            task_id,
            assigned_to=to_agent,
            status=new_status,
            handover_notes=handover_notes.strip(),
        )

    def request_revision(
        self,
        task_id: str,
        reviewer: str,
        revision_notes: str,
    ) -> Dict[str, Any]:
        """Reviewer sends a task back to coder with revision notes."""
        if not revision_notes or not revision_notes.strip():
            raise ValueError("revision_notes are required")
        return self.update_task(
            task_id,
            status="needs_revision",
            handover_notes=revision_notes.strip(),
        )

    def complete_task(self, task_id: str) -> Dict[str, Any]:
        """Mark a task as completed."""
        return self.update_task(task_id, status="completed")

    def delete_task(self, task_id: str) -> bool:
        """Permanently delete a task. Returns True if deleted."""
        def _delete(conn: sqlite3.Connection) -> int:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cur.rowcount

        rows_deleted = self._execute_write(_delete)
        return rows_deleted > 0

    def summary_counts(self) -> Dict[str, int]:
        """Return a {status: count} dict for all tasks."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}


# ── Module-level singleton (lazy, process-scoped) ──
_db_instance: Optional[SharedTaskDB] = None
_db_lock = threading.Lock()


def get_shared_task_db(db_path: Optional[Path] = None) -> SharedTaskDB:
    """Return (or create) the process-level SharedTaskDB singleton."""
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = SharedTaskDB(db_path)
    return _db_instance
