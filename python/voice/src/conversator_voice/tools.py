"""Tool definitions for Gemini Live conversational agent."""

from typing import Any

# Tool definitions that Gemini Live can use to interact with Conversator
CONVERSATOR_TOOLS: list[dict[str, Any]] = [
    # === Project Management Tools ===
    # These tools help set up the project context before coding work begins
    {
        "name": "list_projects",
        "description": """List available projects in the workspace directory.
        Call this when user asks what projects exist, wants to see options,
        or when you need to help them choose a project to work on.
        Returns project names that have version control or project markers.""",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "select_project",
        "description": """Select a project to work on and start the builder automatically.
        Call when user specifies which project they want to work on, like "let's work on my-app".
        Do not ask whether to start the builder — assume yes.""",

        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name of the project folder to select",
                }
            },
            "required": ["project_name"],
        },
    },
    {
        "name": "start_builder",
        "description": """Start (or restart) the coding agent (OpenCode) in the current project directory.
        Use when the user asks to start/restart the builder, or if the builder is not running.
        Usually not needed after select_project because select_project auto-starts the builder.""",

        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "create_project",
        "description": """Create a new project folder in the workspace directory.
        Use when user wants to start a new project from scratch.
        Creates the folder, optionally initializes git, then selects it and starts the builder.
        Example: 'create a new project called my-app' or 'start a new project for the website'.""",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name for the new project folder (use lowercase with dashes, e.g., 'my-new-app')",
                },
                "init_git": {
                    "type": "boolean",
                    "description": "Initialize git repository in the new project. Default: true",
                },
                "start_builder_after": {
                    "type": "boolean",
                    "description": "Automatically select and start the builder in the new project. Default: true",
                },
            },
            "required": ["project_name"],
        },
    },
    {
        "name": "engage_with_project",
        "description": """Select a project (fuzzy match) and engage a subagent in one step.
        Use when the user implies BOTH the project and an action, e.g.:
        - 'brainstorm my calculator app'
        - 'plan an auth flow for the website'

        This avoids extra back-and-forth: it selects the project, starts the builder,
        then begins either planner or brainstormer flow.""",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project name/hint (fuzzy matched)",
                },
                "project_hint": {
                    "type": "string",
                    "description": "Alias for project (for backward compatibility)",
                },
                "subagent": {
                    "type": "string",
                    "enum": ["planner", "brainstormer"],
                    "description": "Which subagent to engage",
                },
                "topic": {
                    "type": "string",
                    "description": "Task/topic to send to the subagent",
                },
                "context": {
                    "type": "string",
                    "description": "Optional extra context",
                },
            },
            "required": ["project", "subagent", "topic"],
        },
    },
    # === Planning and Context Tools ===
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
                    "description": "What the user wants to accomplish, in your words",
                },
                "context": {
                    "type": "string",
                    "description": "Relevant context from the conversation so far",
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "How urgent this task is",
                },
            },
            "required": ["task_description"],
        },
    },
    {
        "name": "continue_planner",
        "description": """Continue an active planner session after the user answers
        the planner's clarifying question(s). Use ONLY after engage_planner returns
        status='needs_input'. Do not call engage_planner again for the same task -
        that would restart the planner and can cause looping questions.""",
        "parameters": {
            "type": "object",
            "properties": {
                "user_response": {
                    "type": "string",
                    "description": "The user's answer to the planner's question(s)",
                }
            },
            "required": ["user_response"],
        },
    },
    {
        "name": "confirm_send_to_subagent",
        "description": """Confirm and send collected answers/context to the active subagent.
        Use after all questions are answered and the user confirms you're ready to send.""",
        "parameters": {
            "type": "object",
            "properties": {
                "additional_context": {
                    "type": "string",
                    "description": "Optional extra context to include when sending",
                }
            },
        },
    },
    {
        "name": "continue_brainstormer",
        "description": """Continue an active brainstorm relay.
        Use after engage_brainstormer returns status='needs_detail' or 'needs_confirmation',
        or when relaying answers back to brainstormer questions.""",
        "parameters": {
            "type": "object",
            "properties": {
                "user_response": {
                    "type": "string",
                    "description": "The user's message/answer/confirmation",
                }
            },
            "required": ["user_response"],
        },
    },
    {
        "name": "lookup_context",
        "description": """Look up relevant context from memory or codebase.
        Use when you or user need to recall past decisions, find code,
        understand previous implementations, or get background on a topic.""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up - be specific"},
                "scope": {
                    "type": "string",
                    "enum": ["memory", "codebase", "both"],
                    "description": "Where to search. Default: both",
                },
            },
            "required": ["query"],
        },
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
                    "description": "Include detailed progress info. Default: false",
                }
            },
        },
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
                "plan_file": {"type": "string", "description": "Path to the plan file to execute"},
                "agent": {
                    "type": "string",
                    "enum": ["auto", "claude-code", "opencode"],
                    "description": "Which agent to use. 'auto' uses routing rules based on complexity.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["plan", "build"],
                    "description": "For claude-code: 'plan' uses Opus for deep planning, 'build' uses Sonnet for implementation",
                },
                "parallel_with": {
                    "type": "string",
                    "description": "Task ID to run in parallel with (agents manage their own worktrees)",
                },
            },
            "required": ["plan_file"],
        },
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
                    "description": "What to remember - be specific and include context",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords for later retrieval",
                },
                "importance": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "How important this memory is",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "cancel_task",
        "description": """Cancel a running or pending task. Use when user
        explicitly asks to stop something or when a task is no longer needed.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID of the task to cancel"},
                "reason": {"type": "string", "description": "Why the task is being canceled"},
            },
            "required": ["task_id"],
        },
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
                    "description": "Include already-read notifications. Default: false",
                }
            },
        },
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
                    "description": "Specific notification IDs to acknowledge. If empty, acknowledges all.",
                }
            },
        },
    },
    {
        "name": "update_working_prompt",
        "description": """Update the working prompt with refined task details as
        they emerge during conversation. Call this as you learn more about what
        the user wants - it builds up the task specification incrementally.""",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title (short, descriptive)"},
                "intent": {
                    "type": "string",
                    "description": "What the user wants to achieve - the goal",
                },
                "requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific requirements gathered from conversation",
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Constraints or things to avoid",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context relevant to the task",
                },
            },
            "required": ["title", "intent"],
        },
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
                    "description": "Brief summary to confirm with user before freezing",
                }
            },
        },
    },
    {
        "name": "quick_dispatch",
        "description": """Execute a simple, quick operation immediately via a fast builder.
        Use for read-only queries (git status, ls, tree, file checks) and simple
        mutations (mkdir, touch, git checkout branch). Operations run through
        the builder layer with proper audit trails.

        NOT for: complex builds, refactoring, destructive operations (rm, force),
        or anything requiring planning. Those should use engage_planner first.""",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["query", "simple_mutation"],
                    "description": "Type: 'query' for read-only (ls, git status), 'simple_mutation' for safe writes (mkdir, touch)",
                },
                "command": {
                    "type": "string",
                    "description": "The command to execute (e.g., 'mkdir my-project', 'git status', 'ls -la')",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory (default: project root)",
                },
            },
            "required": ["operation", "command"],
        },
    },
    {
        "name": "engage_brainstormer",
        "description": """Start a brainstorm relay draft.

        IMPORTANT: this does NOT immediately send anything to a subagent.
        Use it when the user says they want to brainstorm. Then:
        - Ask the user for their full thoughts/details.
        - Ask for confirmation ("Anything else?" / "Want me to send?").
        - Only after confirmation (or silence auto-confirm) will Conversator
          relay the message to the brainstormer subagent in OpenCode.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What to brainstorm or discuss"},
                "context": {"type": "string", "description": "Relevant context for the discussion"},
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any constraints to keep in mind",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "start_subagent_thread",
        "description": """Start a NEW subagent session thread.
        Use when you want multiple concurrent brainstorms or plans.""",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent": {
                    "type": "string",
                    "enum": ["planner", "brainstormer"],
                    "description": "Which subagent to start",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional topic label for the thread",
                },
                "focus": {
                    "type": "boolean",
                    "description": "Whether to focus this thread (default: true)",
                },
            },
            "required": ["subagent"],
        },
    },
    {
        "name": "send_to_thread",
        "description": """Send a message to a thread (non-blocking).
        Use after start_subagent_thread or to continue the focused thread.""",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to send"},
                "thread_id": {
                    "type": "string",
                    "description": "Optional thread_id (defaults to focused thread)",
                },
                "subagent": {
                    "type": "string",
                    "enum": ["planner", "brainstormer"],
                    "description": "Subagent name (required if creating a new thread)",
                },
                "topic": {
                    "type": "string",
                    "description": "Topic label (used when creating a new thread)",
                },
                "create_new_thread": {
                    "type": "boolean",
                    "description": "Create a new thread instead of using an existing one",
                },
                "focus": {
                    "type": "boolean",
                    "description": "Whether to focus the thread (default: true)",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "list_threads",
        "description": """List all active subagent threads.
        Use when you want to see what threads exist and which one is focused.""",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "focus_thread",
        "description": """Focus an existing thread.
        Call when you want future messages to go to a specific thread.""",
        "parameters": {
            "type": "object",
            "properties": {"thread_id": {"type": "string", "description": "Thread ID to focus"}},
            "required": ["thread_id"],
        },
    },
    {
        "name": "open_thread",
        "description": """Open a thread and relay its latest response/questions.
        Use when you want to hear what a thread replied.""",
        "parameters": {
            "type": "object",
            "properties": {"thread_id": {"type": "string", "description": "Thread ID to open"}},
            "required": ["thread_id"],
        },
    },
    {
        "name": "get_builder_plan",
        "description": """Get the plan response from a builder in plan mode.
        Use after dispatch_to_builder with mode='plan' to see what the builder
        proposes before implementation begins.""",
        "parameters": {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "Task ID to get plan for"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "approve_builder_plan",
        "description": """Approve the builder's plan and start implementation.
        Use after reviewing the plan from get_builder_plan. User says
        'looks good', 'start building', 'go ahead', 'implement it', etc.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to approve"},
                "modifications": {
                    "type": "string",
                    "description": "Optional modifications to the plan before building",
                },
            },
            "required": ["task_id"],
        },
    },
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
