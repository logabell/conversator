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
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "select_project",
        "description": """Select a project to work on. This sets the project context
        for the builder. Call when user specifies which project they want to work on,
        like 'let's work on my-app' or 'open the website project'.""",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name of the project folder to select"
                }
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "start_builder",
        "description": """Start the coding agent (OpenCode) in the current project directory.
        Call after selecting a project with select_project. This launches the builder
        so it can execute coding tasks in the selected project. You can combine this
        with select_project in a single turn when user says 'let's work on X'.""",
        "parameters": {
            "type": "object",
            "properties": {}
        }
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
                    "description": "Name for the new project folder (use lowercase with dashes, e.g., 'my-new-app')"
                },
                "init_git": {
                    "type": "boolean",
                    "description": "Initialize git repository in the new project. Default: true"
                },
                "start_builder_after": {
                    "type": "boolean",
                    "description": "Automatically select and start the builder in the new project. Default: true"
                }
            },
            "required": ["project_name"]
        }
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
                    "enum": ["auto", "claude-code", "opencode"],
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
                    "description": "Type: 'query' for read-only (ls, git status), 'simple_mutation' for safe writes (mkdir, touch)"
                },
                "command": {
                    "type": "string",
                    "description": "The command to execute (e.g., 'mkdir my-project', 'git status', 'ls -la')"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory (default: project root)"
                }
            },
            "required": ["operation", "command"]
        }
    },
    {
        "name": "engage_brainstormer",
        "description": """Engage the brainstormer subagent for free-form ideation
        and discussion. Use for exploring ideas, discussing trade-offs,
        thinking through approaches, or creative problem-solving.
        Unlike the planner (which produces prompts), brainstormer is for
        open-ended exploration.""",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "What to brainstorm or discuss"
                },
                "context": {
                    "type": "string",
                    "description": "Relevant context for the discussion"
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any constraints to keep in mind"
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "get_builder_plan",
        "description": """Get the plan response from a builder in plan mode.
        Use after dispatch_to_builder with mode='plan' to see what the builder
        proposes before implementation begins.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to get plan for"
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "approve_builder_plan",
        "description": """Approve the builder's plan and start implementation.
        Use after reviewing the plan from get_builder_plan. User says
        'looks good', 'start building', 'go ahead', 'implement it', etc.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to approve"
                },
                "modifications": {
                    "type": "string",
                    "description": "Optional modifications to the plan before building"
                }
            },
            "required": ["task_id"]
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
