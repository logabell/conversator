"""Threaded subagent session tracking.

A "thread" corresponds to a single OpenCode session ID (ses_...), and allows
multiple concurrent subagent conversations per run.

This is ephemeral runtime state (fresh per run). Persistence is handled via
StateStore inbox items if needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4


ThreadStatus = Literal[
    "idle",
    "waiting_response",
    "has_response",
    "awaiting_user",
    "error",
]


AnnouncementKind = Literal[
    "wait_started",
    "response_ready",
    "info",
    "error",
]


@dataclass
class SubagentThread:
    """A single OpenCode session + its relay metadata."""

    subagent: str
    topic: str
    opencode_session_id: str

    thread_id: str = field(default_factory=lambda: str(uuid4()))
    status: ThreadStatus = "idle"

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    last_user_message: str | None = None
    last_response: str | None = None
    last_error: str | None = None


@dataclass
class PendingAnnouncement:
    """A queued voice announcement delivered at a safe point."""

    text: str
    kind: AnnouncementKind = "info"
    thread_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
