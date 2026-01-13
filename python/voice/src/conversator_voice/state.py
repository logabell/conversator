"""Event-sourced state store for Conversator.

Uses SQLite for persistence with an append-only event log
and derived state tables that can be rebuilt from events.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import (
    ConversatorTask,
    InboxItem,
    TaskEvent,
    TaskMapping,
    TaskStatus,
    EventType,
    create_task_created_payload,
)


# SQL schema for the state database
SCHEMA = """
-- Events table (append-only log)
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    type TEXT NOT NULL,
    task_id TEXT NOT NULL,
    payload TEXT NOT NULL
);

-- Tasks table (derived state, can be rebuilt from events)
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    beads_id TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    project_root TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    working_prompt_path TEXT,
    handoff_prompt_path TEXT,
    builder_session_id TEXT,
    last_event_id INTEGER DEFAULT 0
);

-- Inbox table
CREATE TABLE IF NOT EXISTS inbox (
    inbox_id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    summary TEXT NOT NULL,
    refs TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_at TEXT
);

-- Mappings table
CREATE TABLE IF NOT EXISTS mappings (
    task_id TEXT PRIMARY KEY,
    beads_id TEXT,
    session_id TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_inbox_ack ON inbox(acknowledged_at);
CREATE INDEX IF NOT EXISTS idx_inbox_severity ON inbox(severity);
"""


class StateStore:
    """Event-sourced state store backed by SQLite.

    Events are appended to an immutable log, and derived state
    (tasks, inbox) is updated on each event. On recovery, state
    can be rebuilt by replaying events.
    """

    def __init__(self, db_path: Path | str):
        """Initialize the state store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._event_listeners: list = []
        self._init_schema()

    def add_event_listener(self, callback) -> None:
        """Add a callback to be notified of new events.

        Args:
            callback: Function to call with new events.
                      Signature: callback(event: TaskEvent) -> None
        """
        self._event_listeners.append(callback)

    def remove_event_listener(self, callback) -> None:
        """Remove an event listener.

        Args:
            callback: The callback to remove
        """
        if callback in self._event_listeners:
            self._event_listeners.remove(callback)

    def _init_schema(self) -> None:
        """Initialize database schema."""
        self.conn.executescript(SCHEMA)
        self.conn.commit()

        # Migration: Add project_root column if it doesn't exist
        try:
            self.conn.execute("SELECT project_root FROM tasks LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN project_root TEXT")
            self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    # --- Event Operations ---

    def append_event(self, event: TaskEvent) -> int:
        """Append an event and update derived state.

        Args:
            event: The event to append

        Returns:
            The assigned event_id
        """
        cursor = self.conn.execute(
            """
            INSERT INTO events (time, type, task_id, payload)
            VALUES (?, ?, ?, ?)
            """,
            (
                event.time.isoformat(),
                event.type,
                event.task_id,
                json.dumps(event.payload)
            )
        )
        event_id = cursor.lastrowid
        event.event_id = event_id

        # Update derived state based on event type
        self._apply_event(event)
        self.conn.commit()

        # Notify listeners
        for listener in self._event_listeners:
            try:
                listener(event)
            except Exception:
                # Don't let listener errors break event processing
                pass

        return event_id

    def get_events(
        self,
        task_id: str | None = None,
        event_type: EventType | None = None,
        after_id: int = 0
    ) -> list[TaskEvent]:
        """Get events matching filters.

        Args:
            task_id: Filter by task ID
            event_type: Filter by event type
            after_id: Only return events after this ID

        Returns:
            List of matching events
        """
        query = "SELECT * FROM events WHERE event_id > ?"
        params: list = [after_id]

        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)

        if event_type:
            query += " AND type = ?"
            params.append(event_type)

        query += " ORDER BY event_id ASC"

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _row_to_event(self, row: sqlite3.Row) -> TaskEvent:
        """Convert a database row to TaskEvent."""
        return TaskEvent(
            event_id=row["event_id"],
            time=datetime.fromisoformat(row["time"]),
            type=row["type"],
            task_id=row["task_id"],
            payload=json.loads(row["payload"])
        )

    # --- Task Operations ---

    def get_task(self, task_id: str) -> ConversatorTask | None:
        """Get a task by ID.

        Args:
            task_id: The task ID

        Returns:
            The task or None if not found
        """
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if row:
            return self._row_to_task(row)
        return None

    def get_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 100
    ) -> list[ConversatorTask]:
        """Get tasks matching filters.

        Args:
            status: Filter by status
            limit: Maximum number of tasks to return

        Returns:
            List of matching tasks
        """
        if status:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

        return [self._row_to_task(row) for row in rows]

    def get_active_tasks(self) -> list[ConversatorTask]:
        """Get all tasks that are not done, failed, or canceled."""
        rows = self.conn.execute(
            """
            SELECT * FROM tasks
            WHERE status NOT IN ('done', 'failed', 'canceled')
            ORDER BY priority DESC, updated_at DESC
            """
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def _row_to_task(self, row: sqlite3.Row) -> ConversatorTask:
        """Convert a database row to ConversatorTask."""
        return ConversatorTask(
            task_id=row["task_id"],
            beads_id=row["beads_id"],
            title=row["title"],
            status=row["status"],
            priority=row["priority"],
            project_root=row["project_root"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            working_prompt_path=row["working_prompt_path"],
            handoff_prompt_path=row["handoff_prompt_path"],
            builder_session_id=row["builder_session_id"],
            last_event_id=row["last_event_id"]
        )

    # --- Inbox Operations ---

    def add_inbox_item(self, item: InboxItem) -> None:
        """Add an item to the inbox.

        Args:
            item: The inbox item to add
        """
        self.conn.execute(
            """
            INSERT INTO inbox (inbox_id, severity, summary, refs, created_at, acknowledged_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item.inbox_id,
                item.severity,
                item.summary,
                json.dumps(item.refs),
                item.created_at.isoformat(),
                item.acknowledged_at.isoformat() if item.acknowledged_at else None
            )
        )
        self.conn.commit()

    def get_inbox(
        self,
        unread_only: bool = False,
        severity: str | None = None,
        limit: int = 50
    ) -> list[InboxItem]:
        """Get inbox items.

        Args:
            unread_only: Only return unacknowledged items
            severity: Filter by severity
            limit: Maximum number of items to return

        Returns:
            List of inbox items
        """
        query = "SELECT * FROM inbox WHERE 1=1"
        params: list = []

        if unread_only:
            query += " AND acknowledged_at IS NULL"

        if severity:
            query += " AND severity = ?"
            params.append(severity)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_inbox_item(row) for row in rows]

    def acknowledge_inbox(self, inbox_id: str) -> None:
        """Mark an inbox item as acknowledged.

        Args:
            inbox_id: The inbox item ID
        """
        self.conn.execute(
            "UPDATE inbox SET acknowledged_at = ? WHERE inbox_id = ?",
            (datetime.utcnow().isoformat(), inbox_id)
        )
        self.conn.commit()

    def acknowledge_all_inbox(self) -> int:
        """Mark all unread inbox items as acknowledged.

        Returns:
            Number of items acknowledged
        """
        cursor = self.conn.execute(
            "UPDATE inbox SET acknowledged_at = ? WHERE acknowledged_at IS NULL",
            (datetime.utcnow().isoformat(),)
        )
        self.conn.commit()
        return cursor.rowcount

    def _row_to_inbox_item(self, row: sqlite3.Row) -> InboxItem:
        """Convert a database row to InboxItem."""
        return InboxItem(
            inbox_id=row["inbox_id"],
            severity=row["severity"],
            summary=row["summary"],
            refs=json.loads(row["refs"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None
        )

    # --- Mapping Operations ---

    def set_mapping(self, mapping: TaskMapping) -> None:
        """Set or update a task mapping.

        Args:
            mapping: The mapping to set
        """
        self.conn.execute(
            """
            INSERT OR REPLACE INTO mappings (task_id, beads_id, session_id)
            VALUES (?, ?, ?)
            """,
            (mapping.task_id, mapping.beads_id, mapping.session_id)
        )
        self.conn.commit()

    def get_mapping_by_task(self, task_id: str) -> TaskMapping | None:
        """Get mapping by Conversator task ID."""
        row = self.conn.execute(
            "SELECT * FROM mappings WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if row:
            return TaskMapping(
                task_id=row["task_id"],
                beads_id=row["beads_id"],
                session_id=row["session_id"]
            )
        return None

    def get_mapping_by_beads(self, beads_id: str) -> TaskMapping | None:
        """Get mapping by Beads task ID."""
        row = self.conn.execute(
            "SELECT * FROM mappings WHERE beads_id = ?",
            (beads_id,)
        ).fetchone()

        if row:
            return TaskMapping(
                task_id=row["task_id"],
                beads_id=row["beads_id"],
                session_id=row["session_id"]
            )
        return None

    # --- Event Application (Derived State) ---

    def _apply_event(self, event: TaskEvent) -> None:
        """Apply an event to update derived state.

        Args:
            event: The event to apply
        """
        now = datetime.utcnow().isoformat()

        if event.type == "TaskCreated":
            payload = event.payload
            self.conn.execute(
                """
                INSERT INTO tasks (
                    task_id, title, status, priority, project_root,
                    created_at, updated_at, working_prompt_path, last_event_id
                )
                VALUES (?, ?, 'draft', 0, ?, ?, ?, ?, ?)
                """,
                (
                    event.task_id,
                    payload.get("title", "Untitled Task"),
                    payload.get("project_root"),
                    event.time.isoformat(),
                    now,
                    payload.get("working_prompt_path"),
                    event.event_id
                )
            )
            # Create initial mapping
            self.conn.execute(
                "INSERT OR IGNORE INTO mappings (task_id) VALUES (?)",
                (event.task_id,)
            )

        elif event.type == "WorkingPromptUpdated":
            self.conn.execute(
                """
                UPDATE tasks SET
                    working_prompt_path = ?,
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (
                    event.payload.get("path"),
                    now,
                    event.event_id,
                    event.task_id
                )
            )

        elif event.type == "QuestionsRaised":
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'awaiting_user',
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (now, event.event_id, event.task_id)
            )

        elif event.type == "UserAnswered":
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'refining',
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (now, event.event_id, event.task_id)
            )

        elif event.type == "HandoffFrozen":
            payload = event.payload
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'ready_to_handoff',
                    handoff_prompt_path = ?,
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (
                    payload.get("handoff_md_path"),
                    now,
                    event.event_id,
                    event.task_id
                )
            )

        elif event.type == "BeadsTaskLinked":
            beads_id = event.payload.get("beads_id")
            self.conn.execute(
                """
                UPDATE tasks SET
                    beads_id = ?,
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (beads_id, now, event.event_id, event.task_id)
            )
            # Update mapping
            self.conn.execute(
                "UPDATE mappings SET beads_id = ? WHERE task_id = ?",
                (beads_id, event.task_id)
            )

        elif event.type == "BuilderDispatched":
            payload = event.payload
            session_id = payload.get("session_id")
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'handed_off',
                    builder_session_id = ?,
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (session_id, now, event.event_id, event.task_id)
            )
            # Update mapping
            self.conn.execute(
                "UPDATE mappings SET session_id = ? WHERE task_id = ?",
                (session_id, event.task_id)
            )

        elif event.type == "BuilderStatusChanged":
            new_status = event.payload.get("new_status")
            if new_status == "running":
                task_status = "running"
            elif new_status == "waiting_permission":
                task_status = "awaiting_gate"
            else:
                task_status = "running"

            self.conn.execute(
                """
                UPDATE tasks SET
                    status = ?,
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (task_status, now, event.event_id, event.task_id)
            )

        elif event.type == "GateRequested":
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'awaiting_gate',
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (now, event.event_id, event.task_id)
            )

        elif event.type in ("GateApproved", "GateDenied"):
            # Return to running after gate decision
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'running',
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (now, event.event_id, event.task_id)
            )

        elif event.type == "BuildCompleted":
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'done',
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (now, event.event_id, event.task_id)
            )

        elif event.type == "BuildFailed":
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'failed',
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (now, event.event_id, event.task_id)
            )

        elif event.type == "TaskCanceled":
            self.conn.execute(
                """
                UPDATE tasks SET
                    status = 'canceled',
                    updated_at = ?,
                    last_event_id = ?
                WHERE task_id = ?
                """,
                (now, event.event_id, event.task_id)
            )

    # --- Recovery ---

    def replay_events(self, after_event_id: int = 0) -> int:
        """Rebuild derived state by replaying events.

        Args:
            after_event_id: Replay events after this ID (0 = all)

        Returns:
            Number of events replayed
        """
        if after_event_id == 0:
            # Clear derived state for full replay
            self.conn.execute("DELETE FROM tasks")
            self.conn.execute("DELETE FROM mappings")

        events = self.get_events(after_id=after_event_id)
        for event in events:
            self._apply_event(event)

        self.conn.commit()
        return len(events)

    # --- High-Level Helpers ---

    def create_task(
        self,
        title: str,
        working_prompt_path: str | None = None,
        project_root: str | None = None
    ) -> ConversatorTask:
        """Create a new task with a TaskCreated event.

        Args:
            title: Task title
            working_prompt_path: Optional path to working prompt
            project_root: Optional project directory path

        Returns:
            The created task
        """
        from uuid import uuid4
        task_id = str(uuid4())

        event = TaskEvent(
            type="TaskCreated",
            task_id=task_id,
            payload=create_task_created_payload(title, working_prompt_path, project_root)
        )
        self.append_event(event)

        return self.get_task(task_id)

    def update_task_status(self, task_id: str, event_type: EventType, payload: dict | None = None) -> None:
        """Update a task by emitting an event.

        Args:
            task_id: The task to update
            event_type: The event type
            payload: Optional event payload
        """
        event = TaskEvent(
            type=event_type,
            task_id=task_id,
            payload=payload or {}
        )
        self.append_event(event)

    def cancel_task(self, task_id: str, reason: str = "User requested") -> None:
        """Cancel a task.

        Args:
            task_id: The task to cancel
            reason: Cancellation reason
        """
        from .models import create_task_canceled_payload
        self.update_task_status(
            task_id,
            "TaskCanceled",
            create_task_canceled_payload(reason)
        )
