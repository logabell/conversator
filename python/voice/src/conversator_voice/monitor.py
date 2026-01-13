"""Background monitoring for builder task completion."""

import asyncio
from typing import Callable, TYPE_CHECKING, Any

from .models import InboxItem, create_build_completed_payload, create_build_failed_payload

if TYPE_CHECKING:
    from .state import StateStore
    from .builder_client import BuilderRegistry


class BuilderMonitor:
    """Monitors builder tasks and emits completion events."""

    def __init__(
        self,
        state: "StateStore",
        builders: "BuilderRegistry",
        interval: float = 5.0
    ):
        """Initialize the monitor.

        Args:
            state: State store for task tracking
            builders: Registry of builder clients
            interval: Polling interval in seconds
        """
        self.state = state
        self.builders = builders
        self.interval = interval
        self._running = False
        self._completion_callback: Callable[[str, str, dict], Any] | None = None
        self._task: asyncio.Task | None = None

    async def start(
        self,
        on_completion: Callable[[str, str, dict], Any] | None = None
    ) -> None:
        """Start the monitoring loop.

        Args:
            on_completion: Optional callback when task completes
                          Called with (task_id, status, info_dict)
        """
        self._running = True
        self._completion_callback = on_completion
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_running_tasks()
            except Exception as e:
                print(f"[Monitor] Error checking tasks: {e}")
            await asyncio.sleep(self.interval)

    async def _check_running_tasks(self) -> None:
        """Check all running tasks for completion."""
        running_tasks = [
            t for t in self.state.get_active_tasks()
            if t.status in ("running", "handed_off", "dispatched")
        ]

        for task in running_tasks:
            status = await self._check_task_status(task.task_id)
            if status in ("completed", "failed"):
                await self._handle_completion(task.task_id, task.title, status)

    async def _check_task_status(self, task_id: str) -> str | None:
        """Check builder status for a task.

        Args:
            task_id: Task identifier to check

        Returns:
            Status string or None if not found
        """
        for builder in self.builders:
            status = await builder.get_session_status(task_id)
            if status == "completed":
                return "completed"
            elif status in ("failed", "error"):
                return "failed"
        return None

    async def _handle_completion(
        self,
        task_id: str,
        title: str,
        status: str
    ) -> None:
        """Handle task completion - emit event, create notification.

        Args:
            task_id: Task identifier
            title: Task title
            status: Final status (completed or failed)
        """
        # Emit event to update task state
        if status == "completed":
            self.state.update_task_status(
                task_id,
                "BuildCompleted",
                create_build_completed_payload(task_id, {})
            )
        else:
            self.state.update_task_status(
                task_id,
                "BuildFailed",
                create_build_failed_payload(task_id, "Build failed")
            )

        # Create inbox notification
        severity = "success" if status == "completed" else "error"
        summary = f"Task '{title}' {status}"

        self.state.add_inbox_item(InboxItem(
            severity=severity,
            summary=summary,
            refs={"task_id": task_id}
        ))

        print(f"[Monitor] Task '{title}' ({task_id[:8]}) {status}")

        # Trigger callback if registered
        if self._completion_callback:
            try:
                result = self._completion_callback(task_id, status, {"title": title})
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(f"[Monitor] Callback error: {e}")


async def create_monitor(
    state: "StateStore",
    builders: "BuilderRegistry",
    interval: float = 5.0,
    on_completion: Callable[[str, str, dict], Any] | None = None
) -> BuilderMonitor:
    """Create and start a builder monitor.

    Args:
        state: State store
        builders: Builder registry
        interval: Polling interval
        on_completion: Completion callback

    Returns:
        Running monitor instance
    """
    monitor = BuilderMonitor(state, builders, interval)
    await monitor.start(on_completion)
    return monitor
