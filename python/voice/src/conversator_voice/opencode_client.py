"""OpenCode HTTP client for Conversator.

Uses the OpenCode HTTP server API (v1.1+):
- POST /session
- POST /session/:id/prompt_async
- GET  /session/:id/message
- GET  /agent

Note: /event is a global SSE bus and is not relied on for message content here.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

import aiofiles
import httpx


class OpenCodeClient:
    """Client for communicating with OpenCode agents via HTTP API."""

    def __init__(self, base_url: str = "http://localhost:4096"):
        self.base_url = base_url.rstrip("/")
        # Message polling can run for a while; keep per-request timeouts modest but not tiny.
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=30.0))
        self.active_sessions: dict[str, str] = {}
        self._activity_callback: Callable[[str, str, str, str | None], Awaitable[None]] | None = (
            None
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def health_check(self) -> bool:
        """Check if OpenCode server is healthy."""
        try:
            response = await self.client.get(f"{self.base_url}/agent")
            return response.status_code == 200
        except httpx.RequestError:
            return False

    async def list_agents(self) -> list[dict[str, Any]]:
        """List available agents from OpenCode."""
        try:
            response = await self.client.get(f"{self.base_url}/agent")
            response.raise_for_status()
            return response.json()
        except httpx.RequestError:
            return []

    def set_activity_callback(
        self,
        callback: Callable[[str, str, str, str | None], Awaitable[None]],
    ) -> None:
        """Set callback for activity events during OpenCode polling."""
        self._activity_callback = callback

    async def _emit_activity(
        self,
        agent: str,
        action: str,
        message: str,
        detail: str | None = None,
    ) -> None:
        if not self._activity_callback:
            return
        try:
            await self._activity_callback(agent, action, message, detail)
        except Exception:
            # Never let telemetry crash the client.
            return

    async def engage_subagent(self, agent: str, message: str) -> AsyncIterator[dict[str, Any]]:
        """Create a new session and send a message to a specific agent."""
        if not await self.health_check():
            yield {
                "type": "error",
                "content": f"OpenCode not available at {self.base_url}. Make sure it is running with 'opencode serve'.",
            }
            return

        try:
            session_id = await self._create_session(title=f"Conversator: {agent}")
        except Exception as e:
            yield {"type": "error", "content": f"Failed to create OpenCode session: {e}"}
            return

        self.active_sessions[agent] = session_id
        await self._emit_activity(
            agent,
            "started",
            f"Engaging {agent}",
            message[:200] + "..." if len(message) > 200 else message,
        )
        async for event in self._send_and_poll(session_id=session_id, agent=agent, message=message):
            yield event

    async def continue_session(self, agent: str, message: str) -> AsyncIterator[dict[str, Any]]:
        """Continue an existing agent session."""
        session_id = self.active_sessions.get(agent)
        if not session_id:
            async for event in self.engage_subagent(agent, message):
                yield event
            return

        await self._emit_activity(
            agent,
            "started",
            f"Continuing {agent}",
            message[:200] + "..." if len(message) > 200 else message,
        )

        async for event in self._send_and_poll(session_id=session_id, agent=agent, message=message):
            yield event

    async def _create_session(self, title: str) -> str:
        response = await self.client.post(f"{self.base_url}/session", json={"title": title})
        response.raise_for_status()
        session = response.json()
        session_id = session.get("id") or session.get("session_id")
        if not session_id:
            raise RuntimeError("OpenCode session creation returned no id")
        return session_id

    async def _list_messages(self, session_id: str) -> list[dict[str, Any]]:
        response = await self.client.get(f"{self.base_url}/session/{session_id}/message")
        response.raise_for_status()
        return response.json()

    async def _send_and_poll(
        self, session_id: str, agent: str, message: str
    ) -> AsyncIterator[dict[str, Any]]:
        # Baseline assistant messages so we don't accidentally pick up an older response
        baseline_assistant_ids: set[str] = set()
        try:
            for msg in await self._list_messages(session_id):
                info = msg.get("info", msg)
                if info.get("role") == "assistant":
                    msg_id = info.get("id") or info.get("messageID")
                    if msg_id:
                        baseline_assistant_ids.add(msg_id)
        except Exception:
            baseline_assistant_ids = set()

        # Send the message asynchronously
        response = await self.client.post(
            f"{self.base_url}/session/{session_id}/prompt_async",
            json={"agent": agent, "parts": [{"type": "text", "text": message}]},
        )
        response.raise_for_status()
        await self._emit_activity(
            agent, "request_sent", f"Request sent to {agent}", f"Session: {session_id[:8]}..."
        )

        # Poll for a new assistant message
        start_time = time.time()
        timeout_s = 120.0
        poll_interval = 0.5
        active_message_id: str | None = None
        last_content_length = 0
        stable_polls = 0  # Fallback completion when status is missing

        while time.time() - start_time < timeout_s:
            try:
                messages = await self._list_messages(session_id)
            except Exception as e:
                yield {"type": "error", "content": f"Failed to poll OpenCode messages: {e}"}
                return

            # First, fail fast on OpenCode errors surfaced on messages
            for msg in messages:
                info = msg.get("info", msg)
                error = info.get("error")
                if error:
                    error_data = error.get("data", {}) if isinstance(error, dict) else {}
                    error_msg = error_data.get("message") or str(error)
                    yield {"type": "error", "content": f"OpenCode error: {error_msg}"}
                    return

            # Find candidate assistant messages not in baseline
            candidates: list[tuple[str | None, dict[str, Any], dict[str, Any]]] = []
            for msg in messages:
                info = msg.get("info", msg)
                if info.get("role") != "assistant":
                    continue

                msg_id = info.get("id") or info.get("messageID")
                if msg_id and msg_id in baseline_assistant_ids:
                    continue

                candidates.append((msg_id, msg, info))

            if not candidates:
                await asyncio.sleep(poll_interval)
                poll_interval = min(poll_interval * 1.2, 2.0)
                continue

            # Stick to the first new assistant message we see for this request
            if active_message_id:
                chosen = next((c for c in candidates if c[0] == active_message_id), None)
            else:
                chosen = None

            if not chosen:
                chosen = candidates[-1]
                active_message_id = chosen[0]
                last_content_length = 0
                stable_polls = 0

            _, chosen_msg, chosen_info = chosen

            parts = chosen_msg.get("parts", [])
            content = ""
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    content += part.get("text", "")

            msg_status = chosen_info.get("status", "")
            is_complete = (
                msg_status in ("done", "complete", "finished", "success")
                or chosen_info.get("complete") is True
                or chosen_info.get("finished") is True
                or chosen_info.get("finish") is not None
            )

            if content and len(content) > last_content_length:
                last_content_length = len(content)
                stable_polls = 0
            elif content and len(content) == last_content_length:
                stable_polls += 1

            # Some server builds don't expose message status consistently. As a fallback,
            # if the assistant content stops changing for a while *and* the server isn't
            # providing any completion signal, treat it as complete.
            if content and not is_complete and not msg_status and stable_polls >= 12:
                is_complete = True

            if is_complete:
                duration_ms = (time.time() - start_time) * 1000
                await self._emit_activity(
                    agent,
                    "completed",
                    f"{agent} finished ({duration_ms / 1000:.1f}s)",
                    content[:500] + "..." if len(content) > 500 else content,
                )
                yield {"type": "message", "content": content}
                yield {"type": "complete", "content": content, "duration_ms": duration_ms}
                return

            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.2, 2.0)

        await self._emit_activity(agent, "error", f"{agent} timed out", None)
        yield {"type": "error", "content": f"Timeout waiting for {agent} response"}

    async def get_status(self) -> dict[str, Any]:
        """Read status from cache file (instant, no LLM call)."""
        status_file = Path(".conversator/cache/agent-status.json")
        try:
            async with aiofiles.open(status_file) as f:
                content = await f.read()
                return json.loads(content)
        except FileNotFoundError:
            return {"agents": {}, "tasks": [], "message": "No active tasks"}
        except json.JSONDecodeError:
            return {"agents": {}, "tasks": [], "message": "Status file corrupted"}

    async def update_status(self, agent: str, status: dict[str, Any]) -> None:
        """Update agent status in cache file."""
        from datetime import datetime

        status_file = Path(".conversator/cache/agent-status.json")
        current = await self.get_status()

        current.setdefault("agents", {})
        current["agents"][agent] = {
            **status,
            "updated_at": datetime.utcnow().isoformat(),
        }
        current["updated_at"] = datetime.utcnow().isoformat()

        async with aiofiles.open(status_file, "w") as f:
            await f.write(json.dumps(current, indent=2))

    def clear_session(self, agent: str) -> None:
        """Clear cached session for an agent."""
        self.active_sessions.pop(agent, None)
