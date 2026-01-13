"""OpenCode HTTP client for Conversator subagent orchestration.

Uses the OpenCode HTTP Serve API:
- POST /session - Create new session
- GET  /session/{id} - Get session details
- POST /session/{id}/message - Send message (sync)
- POST /session/{id}/prompt_async - Send message (async)
- GET  /event - SSE real-time events
- GET  /agent - List available agents
"""

import json
from pathlib import Path
from typing import AsyncIterator

import aiofiles
import httpx


class OpenCodeClient:
    """Client for communicating with OpenCode subagents via HTTP API."""

    def __init__(self, base_url: str = "http://localhost:4096"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300)
        self.active_sessions: dict[str, str] = {}

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def health_check(self) -> bool:
        """Check if OpenCode server is healthy."""
        try:
            # Use /agent endpoint - most reliable for OpenCode
            response = await self.client.get(f"{self.base_url}/agent")
            return response.status_code == 200
        except httpx.RequestError:
            return False

    async def list_agents(self) -> list[dict]:
        """List available agents from OpenCode.

        Returns:
            List of agent info dictionaries
        """
        try:
            response = await self.client.get(f"{self.base_url}/agent")
            response.raise_for_status()
            return response.json()
        except httpx.RequestError:
            return []

    async def engage_subagent(
        self, agent: str, message: str
    ) -> AsyncIterator[dict]:
        """Create session and chat with subagent, streaming responses.

        Args:
            agent: Name of the subagent (planner, context-reader, summarizer)
            message: Initial message to send to the agent

        Yields:
            Event dictionaries with type and content
        """
        # Create session with title
        response = await self.client.post(
            f"{self.base_url}/session",
            json={"title": f"Conversator: {agent}"}
        )
        response.raise_for_status()
        session = response.json()
        session_id = session.get("id") or session.get("session_id")
        self.active_sessions[agent] = session_id

        # Send message with @agent mention to invoke subagent
        # OpenCode uses @mention syntax to invoke subagents
        full_message = f"@{agent} {message}"

        # Use async endpoint and stream via SSE
        async for event in self._send_message_stream(session_id, full_message):
            yield event

    async def _send_message_stream(
        self, session_id: str, message: str
    ) -> AsyncIterator[dict]:
        """Send message and stream response via SSE.

        Args:
            session_id: Session ID
            message: Message to send

        Yields:
            Event dictionaries with type and content
        """
        # Send message asynchronously
        response = await self.client.post(
            f"{self.base_url}/session/{session_id}/prompt_async",
            json={"parts": [{"type": "text", "text": message}]}
        )
        response.raise_for_status()

        # Stream events via SSE
        async with self.client.stream(
            "GET",
            f"{self.base_url}/event"
        ) as sse_response:
            async for line in sse_response.aiter_lines():
                if not line:
                    continue

                if line.startswith("data:"):
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                        # Check if event is for our session
                        event_session = event.get("sessionId") or event.get("session_id")
                        if event_session and event_session != session_id:
                            continue

                        # Transform event to our expected format
                        event_type = event.get("type", "message")

                        if event_type in ("assistant.message", "message"):
                            content = event.get("content", "") or event.get("text", "")
                            yield {"type": "message", "content": content}
                        elif event_type == "assistant.done":
                            # Session complete
                            return
                        elif event_type == "error":
                            yield {"type": "error", "content": event.get("message", "Unknown error")}
                            return
                        else:
                            # Pass through other events
                            yield event

                    except json.JSONDecodeError:
                        # Non-JSON line, treat as plain message
                        yield {"type": "message", "content": line}

    async def continue_session(
        self, agent: str, message: str
    ) -> AsyncIterator[dict]:
        """Continue existing session with subagent.

        Args:
            agent: Name of the subagent
            message: Follow-up message

        Yields:
            Event dictionaries with type and content
        """
        session_id = self.active_sessions.get(agent)
        if not session_id:
            # No existing session, create new one
            async for event in self.engage_subagent(agent, message):
                yield event
            return

        # Continue with same session - no need for @mention
        async for event in self._send_message_stream(session_id, message):
            yield event

    async def get_status(self) -> dict:
        """Read status from cache file (instant, no LLM call).

        Returns:
            Status dictionary with agents and tasks
        """
        status_file = Path(".conversator/cache/agent-status.json")
        try:
            async with aiofiles.open(status_file) as f:
                content = await f.read()
                return json.loads(content)
        except FileNotFoundError:
            return {"agents": {}, "tasks": [], "message": "No active tasks"}
        except json.JSONDecodeError:
            return {"agents": {}, "tasks": [], "message": "Status file corrupted"}

    async def update_status(self, agent: str, status: dict) -> None:
        """Update agent status in cache file.

        Args:
            agent: Agent name
            status: Status dictionary to merge
        """
        from datetime import datetime

        status_file = Path(".conversator/cache/agent-status.json")
        current = await self.get_status()

        current["agents"][agent] = {
            **status,
            "updated_at": datetime.utcnow().isoformat()
        }
        current["updated_at"] = datetime.utcnow().isoformat()

        async with aiofiles.open(status_file, "w") as f:
            await f.write(json.dumps(current, indent=2))

    def clear_session(self, agent: str) -> None:
        """Clear cached session for an agent."""
        self.active_sessions.pop(agent, None)
