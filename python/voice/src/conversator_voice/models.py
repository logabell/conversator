"""Data models for Conversator event-sourced state."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4
import json


# Type aliases for status and event types
TaskStatus = Literal[
    "draft",
    "refining",
    "ready_to_handoff",
    "handed_off",
    "running",
    "awaiting_gate",
    "awaiting_user",
    "done",
    "failed",
    "canceled"
]

EventType = Literal[
    "TaskCreated",
    "WorkingPromptUpdated",
    "QuestionsRaised",
    "UserAnswered",
    "HandoffFrozen",
    "BeadsTaskLinked",
    "BuilderDispatched",
    "BuilderStatusChanged",
    "GateRequested",
    "GateApproved",
    "GateDenied",
    "BuildCompleted",
    "BuildFailed",
    "TaskCanceled"
]

InboxSeverity = Literal["info", "success", "warning", "error", "blocking"]

BuilderStatus = Literal[
    "created",
    "running",
    "paused",
    "waiting_permission",
    "completed",
    "failed",
    "aborted"
]


@dataclass
class TaskEvent:
    """An append-only event in the task lifecycle."""

    type: EventType
    task_id: str
    payload: dict = field(default_factory=dict)
    time: datetime = field(default_factory=datetime.utcnow)
    event_id: int | None = None  # Set by database on insert

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_id": self.event_id,
            "time": self.time.isoformat(),
            "type": self.type,
            "task_id": self.task_id,
            "payload": self.payload
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskEvent":
        """Create from dictionary."""
        return cls(
            event_id=data.get("event_id"),
            time=datetime.fromisoformat(data["time"]),
            type=data["type"],
            task_id=data["task_id"],
            payload=data.get("payload", {})
        )


@dataclass
class ConversatorTask:
    """A runtime unit of work inside Conversator."""

    task_id: str = field(default_factory=lambda: str(uuid4()))
    title: str = "Untitled Task"
    status: TaskStatus = "draft"
    priority: int = 0
    project_root: str | None = None  # Target project directory
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    beads_id: str | None = None
    working_prompt_path: str | None = None
    handoff_prompt_path: str | None = None
    builder_session_id: str | None = None
    last_event_id: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "beads_id": self.beads_id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "project_root": self.project_root,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "working_prompt_path": self.working_prompt_path,
            "handoff_prompt_path": self.handoff_prompt_path,
            "builder_session_id": self.builder_session_id,
            "last_event_id": self.last_event_id
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversatorTask":
        """Create from dictionary."""
        return cls(
            task_id=data["task_id"],
            beads_id=data.get("beads_id"),
            title=data["title"],
            status=data["status"],
            priority=data.get("priority", 0),
            project_root=data.get("project_root"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            working_prompt_path=data.get("working_prompt_path"),
            handoff_prompt_path=data.get("handoff_prompt_path"),
            builder_session_id=data.get("builder_session_id"),
            last_event_id=data.get("last_event_id", 0)
        )


@dataclass
class BuilderSession:
    """An execution session with a builder (OpenCode, Claude Code, etc)."""

    session_id: str = field(default_factory=lambda: str(uuid4()))
    provider: str = "opencode"  # opencode | claude_code | etc
    status: BuilderStatus = "created"
    started_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None
    artifacts: dict = field(default_factory=dict)  # diff_summary_path, test_output_path, etc

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "artifacts": self.artifacts
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BuilderSession":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            provider=data.get("provider", "opencode"),
            status=data["status"],
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None,
            artifacts=data.get("artifacts", {})
        )


@dataclass
class InboxItem:
    """A notification in the user's inbox."""

    summary: str
    severity: InboxSeverity = "info"
    refs: dict = field(default_factory=dict)  # beads_id, paths, session_id
    inbox_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    acknowledged_at: datetime | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "inbox_id": self.inbox_id,
            "severity": self.severity,
            "summary": self.summary,
            "refs": self.refs,
            "created_at": self.created_at.isoformat(),
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InboxItem":
        """Create from dictionary."""
        return cls(
            inbox_id=data["inbox_id"],
            severity=data["severity"],
            summary=data["summary"],
            refs=data.get("refs", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            acknowledged_at=datetime.fromisoformat(data["acknowledged_at"]) if data.get("acknowledged_at") else None
        )


@dataclass
class TaskMapping:
    """Maps between Beads task IDs, Conversator task IDs, and builder session IDs."""

    task_id: str
    beads_id: str | None = None
    session_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "beads_id": self.beads_id,
            "session_id": self.session_id
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskMapping":
        """Create from dictionary."""
        return cls(
            task_id=data["task_id"],
            beads_id=data.get("beads_id"),
            session_id=data.get("session_id")
        )


# Event payload helpers

def create_task_created_payload(
    title: str,
    working_prompt_path: str | None = None,
    project_root: str | None = None
) -> dict:
    """Create payload for TaskCreated event."""
    return {
        "title": title,
        "working_prompt_path": working_prompt_path,
        "project_root": project_root
    }


def create_working_prompt_updated_payload(path: str, summary: str | None = None) -> dict:
    """Create payload for WorkingPromptUpdated event."""
    return {
        "path": path,
        "summary": summary
    }


def create_questions_raised_payload(questions: list[str]) -> dict:
    """Create payload for QuestionsRaised event."""
    return {"questions": questions}


def create_user_answered_payload(answers: dict[str, str]) -> dict:
    """Create payload for UserAnswered event."""
    return {"answers": answers}


def create_handoff_frozen_payload(handoff_md_path: str, handoff_json_path: str) -> dict:
    """Create payload for HandoffFrozen event."""
    return {
        "handoff_md_path": handoff_md_path,
        "handoff_json_path": handoff_json_path
    }


def create_beads_task_linked_payload(beads_id: str) -> dict:
    """Create payload for BeadsTaskLinked event."""
    return {"beads_id": beads_id}


def create_builder_dispatched_payload(session_id: str, provider: str) -> dict:
    """Create payload for BuilderDispatched event."""
    return {
        "session_id": session_id,
        "provider": provider
    }


def create_builder_status_changed_payload(session_id: str, old_status: str, new_status: str) -> dict:
    """Create payload for BuilderStatusChanged event."""
    return {
        "session_id": session_id,
        "old_status": old_status,
        "new_status": new_status
    }


def create_gate_requested_payload(gate_type: str, description: str) -> dict:
    """Create payload for GateRequested event."""
    return {
        "gate_type": gate_type,
        "description": description
    }


def create_build_completed_payload(session_id: str, artifacts: dict) -> dict:
    """Create payload for BuildCompleted event."""
    return {
        "session_id": session_id,
        "artifacts": artifacts
    }


def create_build_failed_payload(session_id: str, error: str) -> dict:
    """Create payload for BuildFailed event."""
    return {
        "session_id": session_id,
        "error": error
    }


def create_task_canceled_payload(reason: str) -> dict:
    """Create payload for TaskCanceled event."""
    return {"reason": reason}
