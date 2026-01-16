"""OpenCode SSE client for real-time event streaming.

Connects to OpenCode's /event SSE endpoint and bridges events to the dashboard
WebSocket for real-time session viewing.

Events from OpenCode:
- session.updated: Session created/status changed
- message.updated: Message content updated (streaming)
- session.error: Error occurred
- file.edited: File changes (not used for dashboard)
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Callable, Awaitable
from uuid import uuid4

import httpx

if TYPE_CHECKING:
    from .dashboard.websocket import ConnectionManager

logger = logging.getLogger(__name__)


@dataclass
class OpenCodeSession:
    """Represents an OpenCode session for tracking."""

    session_id: str
    agent_name: str
    status: str = "active"  # active, completed, error
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    task_id: str | None = None
    message_count: int = 0
    source: str = "unknown"  # conversator, builder, external

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "agent_name": self.agent_name,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "task_id": self.task_id,
            "message_count": self.message_count,
            "source": self.source,
        }


@dataclass
class OpenCodeMessage:
    """Represents a message in an OpenCode session."""

    message_id: str
    session_id: str
    role: str  # user, assistant
    parts: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_complete: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role,
            "parts": self.parts,
            "tool_calls": self.tool_calls,
            "created_at": self.created_at.isoformat(),
            "is_complete": self.is_complete,
        }


# Type for session callback: (session_id, event_type, data) -> None
SessionCallback = Callable[[str, str, dict], Awaitable[None]]


class OpenCodeSSEClient:
    """SSE client for real-time OpenCode event streaming.

    Connects to OpenCode's /event endpoint and broadcasts events
    to the dashboard WebSocket for real-time session viewing.
    """

    def __init__(
        self,
        base_url: str,
        ws_manager: "ConnectionManager | None" = None,
    ):
        """Initialize SSE client.

        Args:
            base_url: OpenCode server URL
            ws_manager: Dashboard WebSocket manager for broadcasting
        """
        self.base_url = base_url
        self.ws_manager = ws_manager
        self._sessions: dict[str, OpenCodeSession] = {}
        self._messages: dict[str, dict[str, OpenCodeMessage]] = {}  # session_id -> msg_id -> msg
        self._running = False
        self._task: asyncio.Task | None = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0
        self._session_callbacks: list[SessionCallback] = []
        # Fallback polling state
        self._sse_failures = 0
        self._max_sse_failures = 3
        self._polling_mode = False
        self._polling_interval = 5.0  # Poll every 5 seconds when in fallback mode

    def add_session_callback(self, callback: SessionCallback) -> None:
        """Add callback for session events.

        Args:
            callback: Async function(session_id, event_type, data)
        """
        self._session_callbacks.append(callback)

    async def _emit_session_event(self, session_id: str, event_type: str, data: dict) -> None:
        """Emit session event to callbacks."""
        for callback in self._session_callbacks:
            try:
                await callback(session_id, event_type, data)
            except Exception as e:
                logger.error(f"Session callback error: {e}")

    @property
    def sessions(self) -> dict[str, OpenCodeSession]:
        """Get all tracked sessions."""
        return self._sessions

    @property
    def connection_status(self) -> dict:
        """Get connection status for diagnostics."""
        return {
            "running": self._running,
            "mode": "polling" if self._polling_mode else "sse",
            "sse_failures": self._sse_failures,
            "max_sse_failures": self._max_sse_failures,
            "session_count": len(self._sessions),
            "base_url": self.base_url,
        }

    def get_session(self, session_id: str) -> OpenCodeSession | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def get_session_messages(self, session_id: str) -> list[OpenCodeMessage]:
        """Get messages for a session."""
        session_msgs = self._messages.get(session_id, {})
        return sorted(session_msgs.values(), key=lambda m: m.created_at)

    async def start(self) -> None:
        """Start SSE listener in background.

        Fetches existing sessions first, then starts SSE listener for real-time updates.
        """
        if self._running:
            return

        self._running = True

        # Fetch existing sessions before starting SSE listener
        # This ensures the dashboard shows sessions even if SSE events aren't firing
        try:
            existing = await self.fetch_all_sessions()
            if existing:
                logger.info(f"Pre-loaded {len(existing)} existing sessions from OpenCode")
        except Exception as e:
            logger.warning(f"Could not pre-fetch sessions (OpenCode may not be running): {e}")

        self._task = asyncio.create_task(self._listen_loop())
        logger.info(f"OpenCode SSE client started, connecting to {self.base_url}/event")

    async def stop(self) -> None:
        """Stop SSE listener."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("OpenCode SSE client stopped")

    async def _listen_loop(self) -> None:
        """Main listening loop - SSE with fallback to polling."""
        while self._running:
            if self._polling_mode:
                await self._poll_sessions()
            else:
                try:
                    await self._listen_sse()
                    # Reset failure count on successful SSE connection
                    self._sse_failures = 0
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._sse_failures += 1
                    logger.warning(
                        f"SSE connection error ({self._sse_failures}/{self._max_sse_failures}): {e}"
                    )

                    if self._sse_failures >= self._max_sse_failures:
                        logger.warning(
                            f"SSE failed {self._sse_failures} times, switching to polling mode"
                        )
                        self._polling_mode = True
                        continue

                    await asyncio.sleep(self._reconnect_delay)
                    # Exponential backoff
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2, self._max_reconnect_delay
                    )

    async def _poll_sessions(self) -> None:
        """Fallback polling mode when SSE is unavailable."""
        try:
            sessions = await self.fetch_all_sessions()
            if sessions:
                logger.debug(f"Polled {len(sessions)} sessions")

            # Try SSE again occasionally
            self._sse_failures = max(0, self._sse_failures - 1)
            if self._sse_failures == 0:
                logger.info("Retrying SSE connection...")
                self._polling_mode = False
                self._reconnect_delay = 1.0

        except Exception as e:
            logger.debug(f"Polling error: {e}")

        await asyncio.sleep(self._polling_interval)

    async def _listen_sse(self) -> None:
        """Connect to OpenCode SSE endpoint and process events.

        OpenCode servers have used multiple SSE endpoints over time. We try the
        most common ones in order and use the first that works.
        """
        candidates = (
            # Local OpenCode servers commonly expose SSE here.
            f"{self.base_url}/event",
            f"{self.base_url}/global/event",
            # Some builds / docs mention these, but they may serve the UI instead.
            f"{self.base_url}/event/subscribe",
            f"{self.base_url}/api/event/subscribe",
        )

        async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
            last_error: Exception | None = None

            for url in candidates:
                try:
                    async with client.stream(
                        "GET",
                        url,
                        headers={"Accept": "text/event-stream"},
                    ) as response:
                        if response.status_code != 200:
                            logger.debug(f"SSE candidate {url} returned {response.status_code}")
                            continue

                        content_type = response.headers.get("content-type", "")
                        if "text/event-stream" not in content_type:
                            logger.debug(
                                f"SSE candidate {url} returned non-SSE content-type: {content_type}"
                            )
                            continue

                        logger.info("Connected to OpenCode SSE stream")
                        print(f"[SSE] Connected to {url} - listening for events")
                        self._reconnect_delay = 1.0  # Reset on successful connection

                        event_type = ""
                        event_data = ""

                        async for line in response.aiter_lines():
                            if not self._running:
                                return

                            line = line.strip()

                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                                continue

                            if line.startswith("data:"):
                                chunk = line[5:].strip()
                                # Some servers may send multi-line data; concatenate.
                                event_data = (
                                    (event_data + "\n" + chunk).strip() if event_data else chunk
                                )
                                continue

                            if line == "" and event_data:
                                try:
                                    data = json.loads(event_data)
                                    resolved_type = data.get("type") or event_type
                                    await self._handle_event(resolved_type, data)
                                except json.JSONDecodeError as e:
                                    logger.warning(f"Failed to parse SSE data: {e}")
                                except Exception as e:
                                    logger.error(f"Error handling SSE event: {e}")

                                event_type = ""
                                event_data = ""

                        # Stream ended; try next candidate / reconnect loop.
                        last_error = RuntimeError("SSE stream ended")

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    last_error = e
                    continue

            raise RuntimeError(f"No OpenCode SSE endpoint available: {last_error}")

    async def _handle_event(self, event_type: str, data: dict) -> None:
        """Route SSE events to appropriate handlers.

        OpenCode event payloads vary by server build:
        - sometimes the SSE "event:" name is the event type
        - sometimes the JSON includes a "type" field

        Args:
            event_type: Event type (e.g., "session.updated", "message.part.updated")
            data: Event payload
        """
        if not event_type:
            return

        # Map event types to handlers
        if event_type in ("session.updated", "session.status"):
            await self._on_session_updated(data)
        elif event_type == "message.updated":
            await self._on_message_updated(data)
        elif event_type in ("message.part.updated", "message.part", "message.delta"):
            await self._on_message_part_updated(data)
        elif event_type == "permission.updated":
            await self._on_permission_updated(data)
        elif event_type in ("session.error", "session.status.error"):
            await self._on_session_error(data)
        else:
            logger.debug(f"Unhandled SSE event: {event_type}")

    async def _on_session_updated(self, data: dict) -> None:
        """Handle session.updated event.

        Args:
            data: Event data with session info
        """
        properties = data.get("properties", data)
        info = properties.get("info", {}) if isinstance(properties.get("info", {}), dict) else {}

        session_id = (
            info.get("id")
            or info.get("sessionID")
            or info.get("session_id")
            or properties.get("sessionID")
            or properties.get("session_id")
        )
        if not session_id:
            return

        # Determine agent name from title or agent field
        title = info.get("title") or properties.get("title") or ""
        agent_name = info.get("agent") or properties.get("agent") or "unknown"

        # Parse Conversator session titles
        if title.startswith("Conversator:"):
            agent_name = title.replace("Conversator:", "").strip()

        # Determine source
        source = "external"
        if agent_name.startswith("cvtr-"):
            source = "conversator"
        elif agent_name in ("build", "builder"):
            source = "builder"

        status_type = None
        status_obj = properties.get("status")
        if isinstance(status_obj, dict):
            status_type = status_obj.get("type")
        elif isinstance(status_obj, str):
            status_type = status_obj

        # Create or update session
        if session_id not in self._sessions:
            session = OpenCodeSession(
                session_id=session_id,
                agent_name=agent_name,
                source=source,
                created_at=datetime.now(UTC),
            )
            if status_type:
                session.status = status_type
            self._sessions[session_id] = session
            self._messages[session_id] = {}

            # Broadcast new session to dashboard
            if self.ws_manager:
                await self.ws_manager.broadcast("opencode_session_created", session.to_dict())

            await self._emit_session_event(session_id, "created", session.to_dict())
            logger.info(f"New session tracked: {session_id[:8]}... ({agent_name})")
            print(
                f"[SSE] New session tracked: {session_id[:8]}... agent={agent_name}, source={source}"
            )
        else:
            session = self._sessions[session_id]
            session.updated_at = datetime.now(UTC)
            if status_type:
                session.status = status_type

            # Broadcast update to dashboard
            if self.ws_manager:
                await self.ws_manager.broadcast(
                    "opencode_session_updated",
                    {
                        "session_id": session_id,
                        "status": session.status,
                        "message_count": session.message_count,
                        "updated_at": session.updated_at.isoformat(),
                    },
                )

    async def _on_message_updated(self, data: dict) -> None:
        """Handle message.updated event for streaming content.

        Args:
            data: Event data with message info
        """
        properties = data.get("properties", data)
        info = properties.get("info", properties)

        session_id = (
            info.get("sessionID")
            or info.get("session_id")
            or properties.get("sessionID")
            or properties.get("session_id")
        )
        message_id = (
            info.get("id")
            or info.get("messageID")
            or info.get("message_id")
            or properties.get("messageID")
            or properties.get("message_id")
        )

        if not session_id or not message_id:
            return

        # Get or create message tracking
        if session_id not in self._messages:
            self._messages[session_id] = {}

        session_msgs = self._messages[session_id]
        role = info.get("role") or info.get("sender") or properties.get("role") or "unknown"

        # Extract content from parts
        parts = properties.get("parts", [])
        content = ""
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                content += part.get("text", "")
            elif "text" in part and isinstance(part.get("text"), str):
                # Some server payloads omit explicit type.
                content += part.get("text", "")

        # Check completion status
        msg_status = info.get("status")
        is_complete = (
            msg_status in ("done", "complete", "finished", "success")
            or info.get("complete") is True
            or info.get("finished") is True
        )

        if message_id not in session_msgs:
            # New message
            msg = OpenCodeMessage(
                message_id=message_id,
                session_id=session_id,
                role=role,
                parts=parts,
                is_complete=is_complete,
            )
            session_msgs[message_id] = msg

            # Update session message count
            if session_id in self._sessions:
                self._sessions[session_id].message_count = len(session_msgs)
        else:
            # Update existing message
            msg = session_msgs[message_id]
            old_content_len = sum(len(p.get("text", "")) for p in msg.parts if isinstance(p, dict))
            msg.parts = parts
            msg.is_complete = is_complete

            # Calculate content delta
            new_content_len = len(content)
            if new_content_len > old_content_len:
                content_delta = content[old_content_len:]

                # Broadcast content chunk to dashboard
                if self.ws_manager and content_delta:
                    await self.ws_manager.broadcast(
                        "opencode_message_chunk",
                        {
                            "session_id": session_id,
                            "message_id": message_id,
                            "content_delta": content_delta,
                            "is_complete": is_complete,
                        },
                    )

        # Mark session as completed if message is complete
        if is_complete and session_id in self._sessions:
            session = self._sessions[session_id]
            if role == "assistant":
                session.status = session.status if session.status != "active" else "completed"
                session.updated_at = datetime.now(UTC)

    async def _on_message_part_updated(self, data: dict) -> None:
        """Handle message.part.updated events (streaming deltas + tool state)."""
        properties = data.get("properties", data)

        session_id = properties.get("sessionID") or properties.get("session_id")
        message_id = (
            properties.get("messageID")
            or properties.get("message_id")
            or properties.get("id")
            or properties.get("info", {}).get("id")
        )

        part = properties.get("part") or {}
        delta = properties.get("delta") or part.get("delta")

        if not session_id:
            return

        # Ensure tracking structures exist
        self._messages.setdefault(session_id, {})

        if not message_id:
            message_id = f"part_{uuid4().hex[:8]}"

        msg = self._messages[session_id].get(message_id)
        if not msg:
            msg = OpenCodeMessage(
                message_id=message_id,
                session_id=session_id,
                role=properties.get("role", "assistant"),
                parts=[],
            )
            self._messages[session_id][message_id] = msg

        # Track parts
        msg.parts.append(part)

        # Broadcast streaming delta to dashboard
        if delta and self.ws_manager:
            await self.ws_manager.broadcast(
                "opencode_message_chunk",
                {
                    "session_id": session_id,
                    "message_id": message_id,
                    "content_delta": delta,
                    "is_complete": False,
                    "source_event": "message.part.updated",
                },
            )

        # Broadcast tool updates for visibility
        if self.ws_manager and isinstance(part, dict) and part.get("type") == "tool":
            await self.ws_manager.broadcast(
                "opencode_tool_updated",
                {
                    "session_id": session_id,
                    "message_id": message_id,
                    "tool": part.get("tool"),
                    "status": (part.get("state", {}) or {}).get("status"),
                    "part": part,
                },
            )

    async def _on_permission_updated(self, data: dict) -> None:
        """Handle permission.updated (surfaced in dashboard)."""
        if not self.ws_manager:
            return

        properties = data.get("properties", data)
        await self.ws_manager.broadcast(
            "opencode_permission_updated",
            {
                "title": properties.get("title"),
                "permission": properties,
            },
        )

    async def _on_session_error(self, data: dict) -> None:
        """Handle session.error event.

        Args:
            data: Event data with error info
        """
        properties = data.get("properties", data)
        session_id = properties.get("sessionID") or properties.get("session_id")
        error = properties.get("error", "Unknown error")

        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.status = "error"
            session.updated_at = datetime.now(UTC)

            # Broadcast error to dashboard
            if self.ws_manager:
                await self.ws_manager.broadcast(
                    "opencode_session_updated",
                    {
                        "session_id": session_id,
                        "status": "error",
                        "error": str(error),
                        "updated_at": session.updated_at.isoformat(),
                    },
                )

            await self._emit_session_event(session_id, "error", {"error": str(error)})
            logger.error(f"Session {session_id[:8]}... error: {error}")

    async def fetch_all_sessions(self) -> list[OpenCodeSession]:
        """Fetch all sessions from OpenCode API (for initial load).

        Returns:
            List of OpenCodeSession objects
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/session")
                if response.status_code != 200:
                    return []

                sessions_data = response.json()
                result = []

                for s in sessions_data:
                    info = s.get("info", s)
                    session_id = info.get("id") or info.get("session_id")
                    if not session_id:
                        continue

                    title = info.get("title", "")
                    agent_name = info.get("agent", "unknown")
                    if title.startswith("Conversator:"):
                        agent_name = title.replace("Conversator:", "").strip()

                    source = "external"
                    if agent_name.startswith("cvtr-"):
                        source = "conversator"
                    elif agent_name in ("build", "builder"):
                        source = "builder"

                    session = OpenCodeSession(
                        session_id=session_id,
                        agent_name=agent_name,
                        source=source,
                    )

                    # Track it
                    self._sessions[session_id] = session
                    result.append(session)

                return result

        except Exception as e:
            logger.error(f"Failed to fetch sessions: {e}")
            return []

    async def fetch_session_messages(self, session_id: str) -> list[OpenCodeMessage]:
        """Fetch messages for a session from OpenCode API.

        Args:
            session_id: Session ID

        Returns:
            List of OpenCodeMessage objects
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/session/{session_id}/message")
                if response.status_code != 200:
                    return []

                messages_data = response.json()
                result = []

                for m in messages_data:
                    info = m.get("info", m)
                    message_id = info.get("id") or info.get("messageID")
                    if not message_id:
                        continue

                    msg = OpenCodeMessage(
                        message_id=message_id,
                        session_id=session_id,
                        role=info.get("role", "unknown"),
                        parts=m.get("parts", []),
                        is_complete=True,  # Historical messages are complete
                    )
                    result.append(msg)

                    # Track it
                    if session_id not in self._messages:
                        self._messages[session_id] = {}
                    self._messages[session_id][message_id] = msg

                return result

        except Exception as e:
            logger.error(f"Failed to fetch messages for {session_id}: {e}")
            return []


class MultiSourceSSEManager:
    """Manages SSE connections to multiple OpenCode instances.

    Aggregates sessions from all connected instances with source tagging.
    Supports dynamic addition/removal of sources (e.g., when projects are selected).
    """

    def __init__(self, ws_manager: "ConnectionManager | None" = None):
        """Initialize multi-source manager.

        Args:
            ws_manager: Dashboard WebSocket manager for broadcasting
        """
        self.ws_manager = ws_manager
        self._sources: dict[str, OpenCodeSSEClient] = {}
        self._running = False

    async def add_source(
        self,
        name: str,
        base_url: str,
        start: bool = True,
    ) -> OpenCodeSSEClient:
        """Add a new OpenCode source.

        Args:
            name: Source name (e.g., "layer2", "builder-myproject")
            base_url: OpenCode server URL
            start: Whether to start the SSE client immediately

        Returns:
            The created SSE client
        """
        if name in self._sources:
            logger.warning(f"Source {name} already exists, replacing")
            await self.remove_source(name)

        client = OpenCodeSSEClient(base_url=base_url, ws_manager=self.ws_manager)
        self._sources[name] = client

        if start:
            await client.start()

        logger.info(f"Added OpenCode source: {name} ({base_url})")
        print(f"[SSE Manager] Added source: {name} -> {base_url}")
        return client

    async def remove_source(self, name: str) -> None:
        """Remove an OpenCode source.

        Args:
            name: Source name to remove
        """
        if name not in self._sources:
            return

        client = self._sources.pop(name)
        await client.stop()
        logger.info(f"Removed OpenCode source: {name}")

    async def start_all(self) -> None:
        """Start all SSE clients."""
        self._running = True
        for name, client in self._sources.items():
            try:
                await client.start()
            except Exception as e:
                logger.error(f"Failed to start source {name}: {e}")

    async def stop_all(self) -> None:
        """Stop all SSE clients."""
        self._running = False
        for name, client in list(self._sources.items()):
            try:
                await client.stop()
            except Exception as e:
                logger.error(f"Failed to stop source {name}: {e}")

    def get_all_sessions(self) -> dict[str, list[OpenCodeSession]]:
        """Get all sessions grouped by source.

        Returns:
            Dict mapping source name to list of sessions
        """
        return {name: list(client.sessions.values()) for name, client in self._sources.items()}

    def get_aggregated_sessions(self) -> list[dict]:
        """Get all sessions as a flat list with source tagging.

        Returns:
            List of session dicts with 'instance' field added
        """
        result = []
        for name, client in self._sources.items():
            for session in client.sessions.values():
                session_dict = session.to_dict()
                session_dict["instance"] = name
                result.append(session_dict)

        # Sort by updated_at descending
        result.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return result

    def get_session(self, session_id: str) -> tuple[str | None, OpenCodeSession | None]:
        """Find a session across all sources.

        Args:
            session_id: Session ID to find

        Returns:
            Tuple of (source_name, session) or (None, None) if not found
        """
        for name, client in self._sources.items():
            session = client.get_session(session_id)
            if session:
                return name, session
        return None, None

    def get_session_messages(self, session_id: str) -> list[OpenCodeMessage]:
        """Get messages for a session from any source.

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        for client in self._sources.values():
            messages = client.get_session_messages(session_id)
            if messages:
                return messages
        return []

    async def fetch_session_messages(self, session_id: str) -> list[OpenCodeMessage]:
        """Fetch messages for a session from the appropriate source.

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        source_name, _ = self.get_session(session_id)
        if source_name and source_name in self._sources:
            return await self._sources[source_name].fetch_session_messages(session_id)
        return []

    @property
    def connection_status(self) -> dict:
        """Get aggregated connection status."""
        return {
            "sources": {name: client.connection_status for name, client in self._sources.items()},
            "total_sessions": sum(len(c.sessions) for c in self._sources.values()),
            "running": self._running,
        }

    @property
    def sources(self) -> dict[str, OpenCodeSSEClient]:
        """Get all sources."""
        return self._sources
