"""Tool definitions for Gemini Live conversational agent."""

from typing import Any

# Tool definitions that Gemini Live can use to interact with Conversator
CONVERSATOR_TOOLS: list[dict[str, Any]] = [
    {
        "name": "engage_planner",
        "description": """Engage the planner subagent to refine a task or problem
        into an actionable prompt. Use when user describes something worth acting on.
        The planner will analyze the codebase, ask clarifying questions if needed,
        and produce an optimized prompt for builders.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "What the user wants to accomplish, in your words"
                },
                "context": {
                    "type": "string",
                    "description": "Relevant context from the conversation so far"
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "How urgent this task is"
                }
            },
            "required": ["task_description"]
        }
    },
    {
        "name": "lookup_context",
        "description": """Look up relevant context from memory or codebase.
        Use when you or user need to recall past decisions, find code,
        understand previous implementations, or get background on a topic.""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look up - be specific"
                },
                "scope": {
                    "type": "string",
                    "enum": ["memory", "codebase", "both"],
                    "description": "Where to search. Default: both"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "check_status",
        "description": """Get current status of all running tasks and recent
        completions. Use when user asks what's happening, at natural pauses
        in conversation, or when you need to report progress.""",
        "parameters": {
            "type": "object",
            "properties": {
                "verbose": {
                    "type": "boolean",
                    "description": "Include detailed progress info. Default: false"
                }
            }
        }
    },
    {
        "name": "dispatch_to_builder",
        "description": """Send an optimized prompt to a builder agent for execution.
        Use when planner has produced a ready prompt and user confirms.
        Can specify agent explicitly or let routing decide automatically based
        on task complexity.""",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_file": {
                    "type": "string",
                    "description": "Path to the plan file to execute"
                },
                "agent": {
                    "type": "string",
                    "enum": ["auto", "claude-code", "opencode-fast", "opencode-pro"],
                    "description": "Which agent to use. 'auto' uses routing rules based on complexity."
                },
                "mode": {
                    "type": "string",
                    "enum": ["plan", "build"],
                    "description": "For claude-code: 'plan' uses Opus for deep planning, 'build' uses Sonnet for implementation"
                },
                "parallel_with": {
                    "type": "string",
                    "description": "Task ID to run in parallel with (agents manage their own worktrees)"
                }
            },
            "required": ["plan_file"]
        }
    },
    {
        "name": "add_to_memory",
        "description": """Save an important decision or context for future recall.
        Use when significant decisions are made during conversation, when user
        explicitly asks to remember something, or when capturing important context.""",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "What to remember - be specific and include context"
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords for later retrieval"
                },
                "importance": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "How important this memory is"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "cancel_task",
        "description": """Cancel a running or pending task. Use when user
        explicitly asks to stop something or when a task is no longer needed.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID of the task to cancel"
                },
                "reason": {
                    "type": "string",
                    "description": "Why the task is being canceled"
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "check_inbox",
        "description": """Check for unread notifications and alerts. Use when
        user asks about notifications, updates, things needing attention, or
        what they might have missed.""",
        "parameters": {
            "type": "object",
            "properties": {
                "include_read": {
                    "type": "boolean",
                    "description": "Include already-read notifications. Default: false"
                }
            }
        }
    },
    {
        "name": "acknowledge_inbox",
        "description": """Mark notifications as read/acknowledged. Use when user
        indicates they've seen the notifications or wants to clear them.""",
        "parameters": {
            "type": "object",
            "properties": {
                "inbox_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific notification IDs to acknowledge. If empty, acknowledges all."
                }
            }
        }
    },
    {
        "name": "update_working_prompt",
        "description": """Update the working prompt with refined task details as
        they emerge during conversation. Call this as you learn more about what
        the user wants - it builds up the task specification incrementally.""",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Task title (short, descriptive)"
                },
                "intent": {
                    "type": "string",
                    "description": "What the user wants to achieve - the goal"
                },
                "requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific requirements gathered from conversation"
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Constraints or things to avoid"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context relevant to the task"
                }
            },
            "required": ["title", "intent"]
        }
    },
    {
        "name": "freeze_prompt",
        "description": """Freeze the working prompt into a handoff format ready
        for builders. Call when user confirms they're ready to proceed with the
        task - signals like 'send it', 'let's do it', 'go ahead', etc.""",
        "parameters": {
            "type": "object",
            "properties": {
                "confirm_summary": {
                    "type": "string",
                    "description": "Brief summary to confirm with user before freezing"
                }
            }
        }
    }
]


def get_tool_by_name(name: str) -> dict[str, Any] | None:
    """Get a tool definition by name.

    Args:
        name: Tool name to find

    Returns:
        Tool definition dict or None if not found
    """
    for tool in CONVERSATOR_TOOLS:
        if tool["name"] == name:
            return tool
    return None
