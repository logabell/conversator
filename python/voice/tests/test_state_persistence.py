"""Tests for state persistence (Phase 1 Proof 2)."""

import pytest
import tempfile
import uuid
from datetime import datetime, UTC
from pathlib import Path

from conversator_voice.state import StateStore
from conversator_voice.models import (
    TaskEvent,
    ConversatorTask,
    InboxItem,
    create_task_created_payload,
    create_working_prompt_updated_payload,
)


class TestStateStore:
    """Test StateStore initialization and basic operations."""

    def test_creates_database(self, tmp_path: Path):
        """StateStore creates database file if it doesn't exist."""
        db_path = tmp_path / "state.sqlite"
        assert not db_path.exists()

        store = StateStore(db_path)
        assert db_path.exists()
        store.close()

    def test_creates_schema(self, tmp_path: Path):
        """StateStore creates required tables."""
        db_path = tmp_path / "state.sqlite"
        store = StateStore(db_path)

        # Check tables exist
        cursor = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}

        assert "events" in tables
        assert "tasks" in tables
        assert "inbox" in tables
        assert "mappings" in tables
        store.close()


class TestTaskCreation:
    """Test task creation and event logging."""

    def test_append_task_created_event(self, tmp_path: Path):
        """TaskCreated event creates a task in derived state."""
        db_path = tmp_path / "state.sqlite"
        store = StateStore(db_path)

        task_id = str(uuid.uuid4())
        event = TaskEvent(
            time=datetime.now(UTC),
            type="TaskCreated",
            task_id=task_id,
            payload=create_task_created_payload("Test task title")
        )

        event_id = store.append_event(event)
        assert event_id is not None
        assert event_id > 0

        # Verify task was created
        tasks = store.get_active_tasks()
        assert len(tasks) >= 1

        task = next((t for t in tasks if t.task_id == task_id), None)
        assert task is not None
        assert task.title == "Test task title"
        assert task.status == "draft"

        store.close()

    def test_multiple_tasks(self, tmp_path: Path):
        """Multiple tasks can be created and retrieved."""
        db_path = tmp_path / "state.sqlite"
        store = StateStore(db_path)

        task_ids = []
        for i in range(3):
            task_id = str(uuid.uuid4())
            task_ids.append(task_id)
            event = TaskEvent(
                time=datetime.now(UTC),
                type="TaskCreated",
                task_id=task_id,
                payload=create_task_created_payload(f"Task {i}")
            )
            store.append_event(event)

        tasks = store.get_active_tasks()
        found_ids = {t.task_id for t in tasks}

        for task_id in task_ids:
            assert task_id in found_ids

        store.close()


class TestStatePersistence:
    """Test state persistence across store instances (Phase 1 Proof 2)."""

    def test_tasks_persist_across_restart(self, tmp_path: Path):
        """Tasks survive StateStore close and reopen."""
        db_path = tmp_path / "state.sqlite"

        # Session 1: Create task
        store1 = StateStore(db_path)
        task_id = str(uuid.uuid4())
        event = TaskEvent(
            time=datetime.now(UTC),
            type="TaskCreated",
            task_id=task_id,
            payload=create_task_created_payload("Persistent task")
        )
        store1.append_event(event)
        store1.close()

        # Session 2: Verify task exists
        store2 = StateStore(db_path)
        tasks = store2.get_active_tasks()

        task = next((t for t in tasks if t.task_id == task_id), None)
        assert task is not None
        assert task.title == "Persistent task"
        store2.close()

    def test_events_persist_across_restart(self, tmp_path: Path):
        """Events can be retrieved after restart."""
        db_path = tmp_path / "state.sqlite"

        # Session 1: Create events
        store1 = StateStore(db_path)
        task_id = str(uuid.uuid4())

        event1 = TaskEvent(
            time=datetime.now(UTC),
            type="TaskCreated",
            task_id=task_id,
            payload=create_task_created_payload("Event test task")
        )
        store1.append_event(event1)

        event2 = TaskEvent(
            time=datetime.now(UTC),
            type="WorkingPromptUpdated",
            task_id=task_id,
            payload=create_working_prompt_updated_payload(
                "/path/to/prompt.md",
                "Updated the prompt"
            )
        )
        store1.append_event(event2)
        store1.close()

        # Session 2: Retrieve events
        store2 = StateStore(db_path)
        events = store2.get_events(task_id=task_id)

        assert len(events) == 2
        assert events[0].type == "TaskCreated"
        assert events[1].type == "WorkingPromptUpdated"
        store2.close()

    def test_crash_recovery_simulation(self, tmp_path: Path):
        """Simulate crash recovery by not closing store cleanly."""
        db_path = tmp_path / "state.sqlite"

        # Session 1: Create task, simulate crash (no close)
        store1 = StateStore(db_path)
        task_id = str(uuid.uuid4())
        event = TaskEvent(
            time=datetime.now(UTC),
            type="TaskCreated",
            task_id=task_id,
            payload=create_task_created_payload("Crash test task")
        )
        store1.append_event(event)
        # Note: Not calling store1.close() to simulate crash
        # SQLite should still have committed the data

        # Session 2: Recover
        store2 = StateStore(db_path)
        tasks = store2.get_active_tasks()

        task = next((t for t in tasks if t.task_id == task_id), None)
        assert task is not None
        assert task.title == "Crash test task"
        store2.close()


class TestInbox:
    """Test inbox notification system."""

    def test_add_inbox_item(self, tmp_path: Path):
        """Inbox items can be added and retrieved."""
        db_path = tmp_path / "state.sqlite"
        store = StateStore(db_path)

        item = InboxItem(
            summary="Test notification",
            severity="info",
            refs={"task_id": "123"}
        )
        store.add_inbox_item(item)

        items = store.get_inbox()
        assert len(items) >= 1

        found = next((i for i in items if i.summary == "Test notification"), None)
        assert found is not None
        assert found.severity == "info"
        store.close()

    def test_inbox_acknowledge(self, tmp_path: Path):
        """Inbox items can be acknowledged."""
        db_path = tmp_path / "state.sqlite"
        store = StateStore(db_path)

        item = InboxItem(
            summary="Acknowledgeable notification",
            severity="warning"
        )
        store.add_inbox_item(item)

        # Verify unacknowledged
        unread = store.get_inbox(unread_only=True)
        assert any(i.inbox_id == item.inbox_id for i in unread)

        # Acknowledge
        store.acknowledge_inbox(item.inbox_id)

        # Verify acknowledged
        unread = store.get_inbox(unread_only=True)
        assert not any(i.inbox_id == item.inbox_id for i in unread)
        store.close()
