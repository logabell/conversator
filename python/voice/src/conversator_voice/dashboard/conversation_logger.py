"""Capture and store conversation transcripts for dashboard."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Callable, Literal

ConversationRole = Literal["user", "assistant", "tool_call", "tool_result", "system"]


@dataclass
class ConversationEntry:
    """A single entry in the conversation log."""

    role: ConversationRole
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    # Unique identifier for frontend
    entry_id: int = 0

    # For tool calls
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "entry_id": self.entry_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": self.tool_result,
            "duration_ms": self.duration_ms,
        }


class ConversationLogger:
    """Logs and stores conversation transcripts.

    Maintains an in-memory ring buffer of conversation entries
    and notifies listeners when new entries are added.
    """

    def __init__(self, max_entries: int = 1000):
        """Initialize logger.

        Args:
            max_entries: Maximum entries to keep in memory (ring buffer)
        """
        self.entries: deque[ConversationEntry] = deque(maxlen=max_entries)
        self._listeners: list[Callable[[ConversationEntry], Any]] = []
        self._pending_tool_calls: dict[str, tuple[ConversationEntry, float]] = {}
        self._next_id: int = 1  # Entry ID counter

    def add_listener(self, callback: Callable[[ConversationEntry], Any]) -> None:
        """Add a callback to be notified of new entries.

        Args:
            callback: Function to call with new entries (can be async)
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[ConversationEntry], Any]) -> None:
        """Remove a callback.

        Args:
            callback: The callback to remove
        """
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _get_next_id(self) -> int:
        """Get the next entry ID and increment counter."""
        entry_id = self._next_id
        self._next_id += 1
        return entry_id

    async def _notify_listeners(self, entry: ConversationEntry) -> None:
        """Notify all listeners of a new entry.

        Args:
            entry: The new conversation entry
        """
        for listener in self._listeners:
            try:
                result = listener(entry)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Don't let listener errors break logging
                pass

    async def log_user_speech(
        self,
        transcript: str,
        audio_level: float = 0,
        is_final: bool = True
    ) -> None:
        """Log user speech from Gemini transcription.

        Args:
            transcript: The transcribed text
            audio_level: RMS audio level for display
            is_final: Whether this is a final transcription
        """
        entry = ConversationEntry(
            role="user",
            content=transcript,
            entry_id=self._get_next_id(),
            metadata={
                "audio_level": audio_level,
                "is_final": is_final
            }
        )
        self.entries.append(entry)
        await self._notify_listeners(entry)

    async def log_assistant_response(
        self,
        text: str,
        is_audio: bool = True
    ) -> None:
        """Log assistant response.

        Args:
            text: Response text (or transcript of audio)
            is_audio: Whether this was audio output
        """
        entry = ConversationEntry(
            role="assistant",
            content=text,
            entry_id=self._get_next_id(),
            metadata={"is_audio": is_audio}
        )
        self.entries.append(entry)
        await self._notify_listeners(entry)

    async def log_tool_call_start(
        self,
        tool_name: str,
        tool_args: dict[str, Any]
    ) -> None:
        """Log the start of a tool invocation.

        Args:
            tool_name: Name of the tool called
            tool_args: Arguments passed to the tool
        """
        entry = ConversationEntry(
            role="tool_call",
            content=f"Calling {tool_name}...",
            entry_id=self._get_next_id(),
            tool_name=tool_name,
            tool_args=tool_args,
        )
        self.entries.append(entry)

        # Track start time for duration calculation
        self._pending_tool_calls[tool_name] = (entry, datetime.now(UTC).timestamp())

        await self._notify_listeners(entry)

    async def log_tool_call_complete(
        self,
        tool_name: str,
        tool_result: dict[str, Any]
    ) -> None:
        """Log the completion of a tool invocation.

        Args:
            tool_name: Name of the tool
            tool_result: Result from the tool
        """
        # Find and update the pending tool call
        if tool_name in self._pending_tool_calls:
            entry, start_time = self._pending_tool_calls.pop(tool_name)
            end_time = datetime.now(UTC).timestamp()
            entry.duration_ms = (end_time - start_time) * 1000
            entry.tool_result = tool_result

            # Update content to show completion
            success = tool_result.get("success", not tool_result.get("error"))
            status = "completed" if success else "failed"
            entry.content = f"{tool_name} {status}"

            await self._notify_listeners(entry)
        else:
            # No matching start, log as standalone result
            entry = ConversationEntry(
                role="tool_result",
                content=f"{tool_name} result",
                entry_id=self._get_next_id(),
                tool_name=tool_name,
                tool_result=tool_result,
            )
            self.entries.append(entry)
            await self._notify_listeners(entry)

    async def log_system_event(
        self,
        message: str,
        event_type: str = "info"
    ) -> None:
        """Log a system event.

        Args:
            message: Event message
            event_type: Type of event (info, warning, error)
        """
        entry = ConversationEntry(
            role="system",
            content=message,
            entry_id=self._get_next_id(),
            metadata={"event_type": event_type}
        )
        self.entries.append(entry)
        await self._notify_listeners(entry)

    def get_entries(
        self,
        limit: int = 100,
        offset: int = 0,
        roles: list[ConversationRole] | None = None
    ) -> list[ConversationEntry]:
        """Get conversation entries.

        Args:
            limit: Maximum entries to return
            offset: Skip this many entries
            roles: Filter by role types

        Returns:
            List of entries (newest first)
        """
        entries = list(self.entries)
        if roles:
            entries = [e for e in entries if e.role in roles]

        # Reverse for newest first
        entries = list(reversed(entries))
        return entries[offset:offset + limit]

    def get_recent_transcript(self, count: int = 10) -> str:
        """Get recent conversation as plain text.

        Useful for generating summaries or context.

        Args:
            count: Number of recent entries to include

        Returns:
            Formatted transcript string
        """
        entries = self.get_entries(limit=count)
        lines = []
        for entry in reversed(entries):
            if entry.role == "user":
                lines.append(f"User: {entry.content}")
            elif entry.role == "assistant":
                lines.append(f"Assistant: {entry.content}")
            elif entry.role == "tool_call":
                lines.append(f"[Tool: {entry.tool_name}]")
            elif entry.role == "system":
                lines.append(f"[System: {entry.content}]")
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all entries."""
        self.entries.clear()
        self._pending_tool_calls.clear()
