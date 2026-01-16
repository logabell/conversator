"""Relay-only draft capture state.

This supports flows like:
- User: "I want to brainstorm my app"
- Relay: asks for what to brainstorm, captures the user's message,
  confirms "Anything else?", then sends to the brainstormer subagent.

Subagents remain the brain; this draft is only for staging the user's message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DraftStage = Literal[
    "awaiting_detail",  # waiting for the user to describe what to send
    "awaiting_confirmation",  # waiting for ack/silence to send
]


@dataclass
class RelayDraft:
    target_subagent: str
    project_hint: str | None = None
    topic: str = ""

    message: str = ""
    stage: DraftStage = "awaiting_detail"

    # Prevent repeated auto-confirm injections
    auto_confirm_sent: bool = False
