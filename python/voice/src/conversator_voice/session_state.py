"""Session-level state for Conversator voice sessions.

This module tracks ephemeral state that lives for the duration of a voice
session but is not persisted to the database. This includes:
- Current project selection
- Builder process manager
- Other runtime state

This is separate from the event-sourced StateStore which tracks durable
task/inbox data.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .builder_manager import BuilderManager


@dataclass
class SessionState:
    """Ephemeral state for a voice session.

    This tracks the current project context and builder state during a
    Conversator session. It's not persisted - each new session starts fresh.
    """

    # Current project selection
    current_project: Optional[str] = None
    current_project_path: Optional[Path] = None

    # Builder process manager (created lazily when needed)
    builder_manager: Optional["BuilderManager"] = None

    # Session metadata
    session_started: bool = False

    def is_project_selected(self) -> bool:
        """Check if a project has been selected."""
        return self.current_project is not None and self.current_project_path is not None

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
        await self.stop_builder()
        self.clear_project()
