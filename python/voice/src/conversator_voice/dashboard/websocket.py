"""WebSocket connection manager for real-time dashboard updates."""

import json
from datetime import datetime, UTC
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events to clients."""

    def __init__(self):
        """Initialize the connection manager."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and track a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept
        """
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from tracking.

        Args:
            websocket: The WebSocket connection to remove
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    @property
    def connection_count(self) -> int:
        """Get the number of active connections."""
        return len(self.active_connections)

    async def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast an event to all connected clients.

        Args:
            event_type: Type of event (e.g., 'conversation_entry', 'task_update')
            data: Event payload data
        """
        if not self.active_connections:
            return

        message = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat()
        })

        # Track connections to remove (failed sends)
        dead_connections = []

        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # Connection closed or failed
                dead_connections.append(connection)

        # Clean up dead connections
        for conn in dead_connections:
            self.disconnect(conn)

    async def send_to_one(
        self,
        websocket: WebSocket,
        event_type: str,
        data: dict[str, Any]
    ) -> bool:
        """Send an event to a specific client.

        Args:
            websocket: The target WebSocket connection
            event_type: Type of event
            data: Event payload data

        Returns:
            True if send succeeded, False otherwise
        """
        message = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat()
        })

        try:
            await websocket.send_text(message)
            return True
        except Exception:
            self.disconnect(websocket)
            return False

    async def broadcast_conversation_entry(self, entry_dict: dict[str, Any]) -> None:
        """Broadcast a conversation entry to all clients.

        Convenience method for the most common broadcast type.

        Args:
            entry_dict: Conversation entry as dictionary
        """
        await self.broadcast("conversation_entry", entry_dict)

    async def broadcast_task_update(
        self,
        task_id: str,
        status: str,
        title: str | None = None
    ) -> None:
        """Broadcast a task status update.

        Args:
            task_id: ID of the task
            status: New status
            title: Optional task title
        """
        await self.broadcast("task_update", {
            "task_id": task_id,
            "status": status,
            "title": title
        })

    async def broadcast_inbox_item(
        self,
        inbox_id: str,
        severity: str,
        summary: str
    ) -> None:
        """Broadcast a new inbox notification.

        Args:
            inbox_id: ID of the inbox item
            severity: Severity level
            summary: Notification summary
        """
        await self.broadcast("inbox_item", {
            "inbox_id": inbox_id,
            "severity": severity,
            "summary": summary
        })

    async def broadcast_builder_status(
        self,
        builder_name: str,
        status: str,
        active_tasks: int = 0
    ) -> None:
        """Broadcast a builder status change.

        Args:
            builder_name: Name of the builder
            status: Health status
            active_tasks: Number of active tasks
        """
        await self.broadcast("builder_status", {
            "name": builder_name,
            "status": status,
            "active_tasks": active_tasks
        })

    async def broadcast_system_health(self, health_data: dict[str, Any]) -> None:
        """Broadcast system health update.

        Args:
            health_data: System health information
        """
        await self.broadcast("system_health", health_data)
