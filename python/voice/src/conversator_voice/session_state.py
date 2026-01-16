"""Session-level state for Conversator voice sessions.

This module tracks ephemeral state that lives for the duration of a voice
session but is not persisted to the database. This includes:
- Current project selection
- Builder process manager
- Other runtime state

This is separate from the event-sourced StateStore which tracks durable
task/inbox data.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .relay_draft import RelayDraft
from .subagent_conversation import SubagentConversationState
from .subagent_threads import AnnouncementKind, PendingAnnouncement, SubagentThread

if TYPE_CHECKING:
    from .builder_manager import BuilderManager


@dataclass
class SessionState:
    """Ephemeral state for a voice session.

    This tracks runtime-only state that should not be persisted across runs.
    """

    current_project: str | None = None
    current_project_path: Path | None = None

    builder_manager: BuilderManager | None = None

    session_started: bool = False

    active_subagent_conversation: SubagentConversationState | None = None
    active_draft: RelayDraft | None = None

    last_user_speech_time: float = 0.0
    last_user_transcript: str = ""

    waiting_thread_ids: set[str] = field(default_factory=set)
    waiting_music_preamble_queued: bool = False
    waiting_music_preamble_delivered: bool = False

    _announcement_queue: deque[PendingAnnouncement] = field(default_factory=deque)

    threads: dict[str, SubagentThread] = field(default_factory=dict)
    focused_thread_id: str | None = None

    _tasks: set[asyncio.Task] = field(default_factory=set, repr=False)

    def is_project_selected(self) -> bool:
        """Check if a project has been selected."""
        return self.current_project is not None and self.current_project_path is not None

    def clear_conversation(self) -> None:
        """Clear any active subagent Q&A and relay drafts."""
        self.active_subagent_conversation = None
        self.active_draft = None

    def create_thread(
        self,
        subagent: str,
        topic: str,
        session_id: str,
        focus: bool = True,
    ) -> SubagentThread:
        """Create and track a new thread for a subagent session."""
        thread = SubagentThread(subagent=subagent, topic=topic, opencode_session_id=session_id)
        self.threads[thread.thread_id] = thread
        if focus:
            self.focused_thread_id = thread.thread_id
        return thread

    def get_thread(self, thread_id: str) -> SubagentThread | None:
        """Fetch a thread by id."""
        return self.threads.get(thread_id)

    def get_focused_thread(self) -> SubagentThread | None:
        """Return the currently focused thread, if any."""
        if not self.focused_thread_id:
            return None
        return self.threads.get(self.focused_thread_id)

    def focus_thread(self, thread_id: str) -> None:
        """Set focus to a thread."""
        if thread_id in self.threads:
            self.focused_thread_id = thread_id

    def track_task(self, task: asyncio.Task) -> None:
        """Track a background task and remove it on completion."""
        self._tasks.add(task)

        def _cleanup(_task: asyncio.Task) -> None:
            self._tasks.discard(_task)

        task.add_done_callback(_cleanup)

    def enqueue_announcement(
        self,
        text: str,
        kind: AnnouncementKind = "info",
        thread_id: str | None = None,
    ) -> None:
        """Queue a short announcement for delivery at the next safe point."""
        self._announcement_queue.append(
            PendingAnnouncement(text=text, kind=kind, thread_id=thread_id)
        )

    def pop_announcement(self) -> PendingAnnouncement | None:
        """Pop the next pending announcement, if any."""
        if not self._announcement_queue:
            return None
        return self._announcement_queue.popleft()

    def set_thread_waiting(self, thread_id: str, is_waiting: bool) -> None:
        """Update waiting set for music/UX policy."""
        if is_waiting:
            self.waiting_thread_ids.add(thread_id)
        else:
            self.waiting_thread_ids.discard(thread_id)

    def is_builder_running(self) -> bool:
        """Check if the builder is currently running."""
        if self.builder_manager:
            return self.builder_manager.is_running
        return False

    def clear_project(self) -> None:
        """Clear the current project selection."""
        self.current_project = None
        self.current_project_path = None

    async def stop_builder(self) -> None:
        """Stop the builder if running."""
        if self.builder_manager:
            await self.builder_manager.stop()

    async def cleanup(self) -> None:
        """Clean up session resources."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        await self.stop_builder()
        self.clear_project()
        self.clear_conversation()
        self.waiting_thread_ids.clear()
        self.waiting_music_preamble_queued = False
        self.waiting_music_preamble_delivered = False
        self._announcement_queue.clear()
        self.threads.clear()
        self.focused_thread_id = None
