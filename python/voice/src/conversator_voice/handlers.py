"""Tool handlers for Conversator - dispatches to subagents and Beads."""

import asyncio
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

import aiofiles

from .opencode_client import OpenCodeClient
from .builder_client import OpenCodeBuilder, BuilderRegistry
from .builder_manager import BuilderManager
from .session_state import SessionState

if TYPE_CHECKING:
    from .config import ConversatorConfig
    from .state import StateStore
    from .prompt_manager import PromptManager


class ToolHandler:
    """Handles tool calls from Gemini Live, dispatching to subagents and Beads."""

    def __init__(
        self,
        opencode: OpenCodeClient,
        state: "StateStore | None" = None,
        prompt_manager: "PromptManager | None" = None,
        current_task_id: str | None = None,
        config: "ConversatorConfig | None" = None,
        session_state: "SessionState | None" = None,
    ):
        """Initialize tool handler.

        Args:
            opencode: OpenCode client for subagent communication
            state: Optional state store for task/inbox queries
            prompt_manager: Optional prompt manager for working/handoff prompts
            current_task_id: Optional current task ID for prompt operations
            config: Optional configuration for builders and project settings
            session_state: Optional session state for project/builder tracking
        """
        self.opencode = opencode
        self.state = state
        self.prompt_manager = prompt_manager
        self.current_task_id = current_task_id
        self.config = config
        self.session_state = session_state or SessionState()
        self.planner_session_active = False
        self._memory_index_path = Path(".conversator/memory/index.yaml")
        self._atomic_memory_path = Path(".conversator/memory/atomic.jsonl")

        # Initialize builder registry from config
        self.builders = BuilderRegistry()
        self._init_builders()

    def _init_builders(self) -> None:
        """Initialize builder clients from config."""
        if not self.config:
            return

        for name, builder_config in self.config.builders.items():
            builder = OpenCodeBuilder(
                name=name,
                base_url=f"http://localhost:{builder_config.port}",
                model=builder_config.model,
            )
            self.builders.register(name, builder)

    # === Project Management Handlers ===

    async def handle_list_projects(self) -> dict[str, Any]:
        """List available projects in the workspace directory.

        Returns:
            List of project names with voice-friendly summary
        """
        if not self.config:
            return {"error": "Configuration not available.", "projects": []}

        root = Path(self.config.root_project_dir)
        if not root.exists():
            return {"error": f"Workspace directory not found: {root}", "projects": []}

        projects = []
        project_markers = [
            ".git",
            "pyproject.toml",
            "package.json",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
            "build.gradle",
        ]

        for item in root.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                # Check if it looks like a project
                is_project = any((item / marker).exists() for marker in project_markers)
                if is_project:
                    projects.append(item.name)

        projects.sort()

        if not projects:
            return {
                "summary": f"No projects found in {root}. You can create a new one.",
                "projects": [],
                "workspace": str(root),
            }

        # Build voice-friendly summary
        if len(projects) <= 5:
            summary = f"Found {len(projects)} projects: {', '.join(projects)}."
        else:
            summary = f"Found {len(projects)} projects: {', '.join(projects[:5])}, and {len(projects) - 5} more."

        return {"summary": summary, "projects": projects, "workspace": str(root)}

    async def handle_select_project(self, project_name: str) -> dict[str, Any]:
        """Select a project to work on.

        Args:
            project_name: Name of the project folder to select

        Returns:
            Confirmation with project path
        """
        if not self.config:
            return {"error": "Configuration not available."}

        project_path = Path(self.config.root_project_dir) / project_name

        if not project_path.exists():
            # List available projects to help user
            available = await self.handle_list_projects()
            return {
                "error": f"Project '{project_name}' not found.",
                "suggestion": f"Available projects: {', '.join(available.get('projects', [])[:5])}",
            }

        if not project_path.is_dir():
            return {"error": f"'{project_name}' is not a directory."}

        # Update session state
        self.session_state.current_project = project_name
        self.session_state.current_project_path = project_path

        return {
            "summary": f"Selected project: {project_name}",
            "project_name": project_name,
            "project_path": str(project_path),
            "hint": "Call start_builder to launch the coding agent in this project.",
        }

    async def handle_start_builder(self) -> dict[str, Any]:
        """Start the builder (OpenCode) in the current project directory.

        Returns:
            Confirmation that builder is starting/started
        """
        if not self.session_state.current_project_path:
            return {
                "error": "No project selected. Use select_project first.",
                "hint": "Call list_projects to see available options.",
            }

        project_path = self.session_state.current_project_path
        project_name = self.session_state.current_project

        # Get builder port from config
        builder_port = 8001
        if self.config and "opencode" in self.config.builders:
            builder_port = self.config.builders["opencode"].port

        # Create and start builder manager if needed
        if not self.session_state.builder_manager:
            self.session_state.builder_manager = BuilderManager(port=builder_port)

        # Check if already running in same project
        if self.session_state.builder_manager.is_running:
            current_project = self.session_state.builder_manager.project_name
            if current_project == project_name:
                return {
                    "summary": f"Builder already running in {project_name}.",
                    "project_name": project_name,
                    "status": "running",
                }
            else:
                # Different project - stop and restart
                await self.session_state.builder_manager.stop()

        # Start the builder
        success = await self.session_state.builder_manager.start(str(project_path))

        if success:
            # Update builder client URL to point to running instance
            builder = self.builders.get("opencode")
            if builder:
                builder.base_url = f"http://localhost:{builder_port}"

            return {
                "summary": f"Builder started in {project_name}. Ready to code!",
                "project_name": project_name,
                "project_path": str(project_path),
                "port": builder_port,
                "status": "running",
            }
        else:
            return {
                "error": f"Failed to start builder in {project_name}.",
                "project_name": project_name,
                "hint": "Check if OpenCode is installed: which opencode",
            }

    async def handle_create_project(
        self, project_name: str, init_git: bool = True, start_builder_after: bool = True
    ) -> dict[str, Any]:
        """Create a new project folder in the workspace directory.

        Args:
            project_name: Name for the new project folder
            init_git: Whether to initialize git in the new project
            start_builder_after: Whether to select and start builder after creation

        Returns:
            Confirmation with project path and status
        """
        if not self.config:
            return {"error": "Configuration not available."}

        # Sanitize project name (lowercase, dashes instead of spaces)
        safe_name = project_name.lower().replace(" ", "-").replace("_", "-")
        # Remove any characters that aren't alphanumeric or dashes
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")

        if not safe_name:
            return {"error": "Invalid project name. Use letters, numbers, and dashes."}

        project_path = Path(self.config.root_project_dir) / safe_name

        if project_path.exists():
            return {
                "error": f"Project '{safe_name}' already exists.",
                "hint": f"Use select_project to work on it, or choose a different name.",
            }

        try:
            # Create the project directory
            project_path.mkdir(parents=True, exist_ok=False)
            print(f"[create_project] Created directory: {project_path}")

            # Initialize git if requested
            if init_git:
                result = subprocess.run(
                    ["git", "init"],
                    cwd=str(project_path),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    print(f"[create_project] Initialized git in {safe_name}")
                else:
                    print(f"[create_project] Git init failed: {result.stderr}")

            # Select and start builder if requested
            if start_builder_after:
                # Select the project
                self.session_state.current_project = safe_name
                self.session_state.current_project_path = project_path

                # Start the builder
                builder_result = await self.handle_start_builder()

                return {
                    "summary": f"Created project '{safe_name}' and started the builder. Ready to code!",
                    "project_name": safe_name,
                    "project_path": str(project_path),
                    "git_initialized": init_git,
                    "builder_status": builder_result.get("status", "unknown"),
                }
            else:
                return {
                    "summary": f"Created project '{safe_name}'. Use select_project to start working on it.",
                    "project_name": safe_name,
                    "project_path": str(project_path),
                    "git_initialized": init_git,
                    "hint": "Call select_project and start_builder to begin coding.",
                }

        except PermissionError:
            return {"error": f"Permission denied creating project at {project_path}"}
        except Exception as e:
            return {"error": f"Failed to create project: {str(e)}"}

    # === Planning and Context Handlers ===

    async def handle_engage_planner(
        self, task_description: str, context: str = "", urgency: str = "normal"
    ) -> dict[str, Any]:
        """Engage planner subagent to refine a task.

        Args:
            task_description: What the user wants to accomplish
            context: Additional context from conversation
            urgency: Task urgency level

        Returns:
            Status dict with plan file or questions
        """
        message = task_description
        if context:
            message = f"{task_description}\n\nContext: {context}"
        if urgency != "normal":
            message = f"[{urgency.upper()} PRIORITY]\n{message}"

        responses: list[str] = []
        plan_file: str | None = None

        async for event in self.opencode.engage_subagent("planner", message):
            content = event.get("content", "")

            if event.get("type") == "message":
                responses.append(content)

            # Check if planner signaled completion
            if "READY_FOR_BUILDER:" in content:
                plan_file = self._extract_filename(content)
                self.planner_session_active = False
                return {
                    "status": "ready",
                    "plan_file": plan_file,
                    "summary": responses[-1] if responses else "Plan ready",
                }

        # Planner is asking questions - keep session active
        self.planner_session_active = True
        return {
            "status": "needs_input",
            "questions": responses[-1] if responses else "Need more information",
        }

    async def handle_planner_response(self, user_response: str) -> dict[str, Any]:
        """Continue planner conversation with user's answer.

        Args:
            user_response: User's answer to planner's questions

        Returns:
            Status dict with plan file or more questions
        """
        async for event in self.opencode.continue_session("planner", user_response):
            content = event.get("content", "")

            if "READY_FOR_BUILDER:" in content:
                self.planner_session_active = False
                filename = self._extract_filename(content)
                return {"status": "ready", "plan_file": filename}
            elif event.get("type") == "message":
                self.planner_session_active = True
                return {"status": "needs_input", "questions": content}

        self.planner_session_active = True
        return {"status": "error", "message": "No response from planner"}

    async def handle_continue_planner(self, user_response: str) -> dict[str, Any]:
        """Continue an active planner session.

        Use this after engage_planner returns status='needs_input'. Calling engage_planner
        again for the same task can restart the planner and lead to looping questions.
        """
        if not self.planner_session_active:
            return {
                "status": "error",
                "error": "Planner session is not active. Call engage_planner first.",
            }

        return await self.handle_planner_response(user_response)

    async def handle_lookup_context(self, query: str, scope: str = "both") -> dict[str, Any]:
        """Look up context from memory or codebase.

        Args:
            query: What to look up
            scope: Where to search (memory, codebase, both)

        Returns:
            Context summary suitable for voice
        """
        async for event in self.opencode.engage_subagent("context-reader", query):
            if event.get("type") == "message":
                return {"context": event["content"]}

        return {"context": "No relevant context found"}

    async def handle_check_status(self, verbose: bool = False) -> dict[str, Any]:
        """Get status of all running tasks.

        Args:
            verbose: Include detailed progress info

        Returns:
            Status summary from state store and external sources
        """
        status: dict[str, Any] = {}

        # Get status from local state store (primary source)
        if self.state:
            active_tasks = self.state.get_active_tasks()
            status["tasks"] = [
                {"task_id": t.task_id[:8], "title": t.title, "status": t.status}
                for t in active_tasks
            ]
            status["active_count"] = len(active_tasks)

            # Get unread inbox count
            unread = self.state.get_inbox(unread_only=True)
            status["unread_notifications"] = len(unread)

            # Voice-friendly summary
            if len(active_tasks) == 0:
                status["summary"] = "No active tasks."
            elif len(active_tasks) == 1:
                t = active_tasks[0]
                status["summary"] = f"One active task: {t.title}, status {t.status}."
            else:
                status["summary"] = f"{len(active_tasks)} active tasks."

            if unread:
                status["summary"] += f" {len(unread)} unread notifications."

        # Also check OpenCode status
        opencode_status = await self.opencode.get_status()
        if opencode_status:
            status["opencode"] = opencode_status

        # Also check Beads for task status
        try:
            result = subprocess.run(
                ["bd", "status", "--json"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                beads_status = json.loads(result.stdout)
                status["beads_tasks"] = beads_status
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass

        return status

    async def handle_dispatch_to_builder(
        self,
        plan_file: str,
        agent: str = "auto",
        mode: str = "build",
        parallel_with: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch task to builder agent via Beads.

        Args:
            plan_file: Path to the plan file
            agent: Which agent (auto, claude-code, opencode-fast, opencode-pro)
            mode: For claude-code: plan (Opus) or build (Sonnet)
            parallel_with: Task ID to run in parallel with

        Returns:
            Dispatch confirmation with task ID
        """
        # Get project_root from current task
        project_root = None
        if self.current_task_id and self.state:
            task = self.state.get_task(self.current_task_id)
            if task:
                project_root = task.project_root

        # Fall back to config's root_project_dir if no task-specific root
        if not project_root and self.config:
            project_root = self.config.root_project_dir

        # Validate plan file exists
        plan_path = Path(plan_file)
        if not plan_path.exists():
            # Check in drafts
            draft_path = Path(f".conversator/plans/drafts/{plan_file}")
            if draft_path.exists():
                plan_path = draft_path
            else:
                return {"error": f"Plan file not found: {plan_file}"}

        # Auto-route if not specified
        if agent == "auto":
            agent = await self._auto_route(plan_path)

        # Try to dispatch via builder client if available
        builder = self.builders.get(agent)
        if builder:
            if await builder.health_check():
                # Use plan mode or build mode based on mode parameter
                if mode == "plan":
                    result = await builder.dispatch_task_plan_mode(
                        task_id=self.current_task_id or "unknown",
                        prompt_path=str(plan_path),
                        project_root=project_root,
                    )
                else:
                    result = await builder.dispatch_task(
                        task_id=self.current_task_id or "unknown",
                        prompt_path=str(plan_path),
                        project_root=project_root,
                    )

                if result.get("dispatched"):
                    # Move plan to active
                    active_path = Path(f".conversator/plans/active/{plan_path.name}")
                    active_path.parent.mkdir(parents=True, exist_ok=True)
                    plan_path.rename(active_path)

                    if mode == "plan":
                        return {
                            "dispatched": True,
                            "task_id": self.current_task_id,
                            "agent": agent,
                            "mode": "plan",
                            "session_id": result.get("session_id"),
                            "project_root": project_root,
                            "awaiting_review": True,
                            "message": f"Sent to {agent} in plan mode. Use get_builder_plan to review the proposal.",
                        }
                    else:
                        return {
                            "dispatched": True,
                            "task_id": self.current_task_id,
                            "agent": agent,
                            "mode": "build",
                            "session_id": result.get("session_id"),
                            "project_root": project_root,
                            "message": f"Sent to {agent}: {plan_path.name}"
                            + (f" (project: {project_root})" if project_root else ""),
                        }
                else:
                    return {
                        "dispatched": False,
                        "error": result.get("error", "Failed to dispatch to builder"),
                        "agent": agent,
                    }
            else:
                return {
                    "dispatched": False,
                    "error": f"Builder {agent} is not responding",
                    "agent": agent,
                }

        # Fall back to Beads for claude-code or unknown agents
        cmd = ["bd", "create", f"--file={plan_path}", f"--assign={agent}", f"--meta=mode:{mode}"]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                return {"error": f"Failed to create task: {result.stderr}", "dispatched": False}

            task_id = result.stdout.strip()

            # Move plan to active
            active_path = Path(f".conversator/plans/active/{plan_path.name}")
            active_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.rename(active_path)

            # Notify agent based on type
            if agent == "claude-code":
                await self._invoke_claude_code(task_id, str(active_path), mode)

            # Update status cache
            await self.opencode.update_status(
                agent,
                {
                    "task_id": task_id,
                    "status": "dispatched",
                    "plan_file": str(active_path),
                    "mode": mode,
                },
            )

            return {
                "dispatched": True,
                "task_id": task_id,
                "agent": agent,
                "mode": mode,
                "project_root": project_root,
                "message": f"Sent to {agent}: {plan_path.name}"
                + (f" (project: {project_root})" if project_root else ""),
            }

        except subprocess.TimeoutExpired:
            return {"error": "Beads command timed out", "dispatched": False}
        except FileNotFoundError:
            return {"error": "Beads (bd) not installed", "dispatched": False}

    async def handle_add_to_memory(
        self, content: str, keywords: list[str] | None = None, importance: str = "normal"
    ) -> dict[str, Any]:
        """Save something to memory for future recall.

        Args:
            content: What to remember
            keywords: Keywords for retrieval
            importance: How important this memory is

        Returns:
            Confirmation of memory saved
        """
        memory_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "content": content,
            "keywords": keywords or [],
            "importance": importance,
        }

        # Append to atomic memory
        async with aiofiles.open(self._atomic_memory_path, "a") as f:
            await f.write(json.dumps(memory_entry) + "\n")

        # Update keyword index
        await self._update_memory_index(content, keywords or [])

        return {"saved": True, "message": f"Got it, I'll remember that."}

    async def handle_cancel_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        """Cancel a running or pending task.

        Args:
            task_id: Task ID to cancel
            reason: Why it's being canceled

        Returns:
            Cancellation confirmation
        """
        try:
            cmd = ["bd", "cancel", task_id]
            if reason:
                cmd.extend(["--reason", reason])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                return {"canceled": True, "task_id": task_id}
            else:
                return {"canceled": False, "error": result.stderr}

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return {"canceled": False, "error": str(e)}

    async def handle_check_inbox(self, include_read: bool = False) -> dict[str, Any]:
        """Check for notifications in the inbox.

        Args:
            include_read: Whether to include already-read notifications

        Returns:
            Voice-friendly summary of notifications
        """
        if not self.state:
            return {"summary": "Inbox not available.", "count": 0}

        items = self.state.get_inbox(unread_only=not include_read)

        if not items:
            return {
                "summary": "No notifications." if not include_read else "No notifications at all.",
                "count": 0,
            }

        # Group by severity for voice summary
        blocking = [i for i in items if i.severity == "blocking"]
        errors = [i for i in items if i.severity == "error"]
        warnings = [i for i in items if i.severity == "warning"]
        info = [i for i in items if i.severity in ("info", "success")]

        # Build voice-friendly summary
        parts = []
        if blocking:
            parts.append(f"{len(blocking)} blocking")
        if errors:
            parts.append(f"{len(errors)} {'error' if len(errors) == 1 else 'errors'}")
        if warnings:
            parts.append(f"{len(warnings)} {'warning' if len(warnings) == 1 else 'warnings'}")
        if info:
            parts.append(f"{len(info)} info")

        summary = f"{len(items)} notifications: " + ", ".join(parts) + "."

        # Include the most important one
        important = blocking[0] if blocking else (errors[0] if errors else items[0])
        summary += f" Most important: {important.summary}"

        return {
            "summary": summary,
            "count": len(items),
            "items": [
                {"inbox_id": i.inbox_id, "severity": i.severity, "summary": i.summary}
                for i in items[:5]  # Limit for voice
            ],
        }

    async def handle_acknowledge_inbox(self, inbox_ids: list[str] | None = None) -> dict[str, Any]:
        """Acknowledge/mark notifications as read.

        Args:
            inbox_ids: Specific IDs to acknowledge, or None for all

        Returns:
            Confirmation of acknowledgment
        """
        if not self.state:
            return {"acknowledged": 0, "error": "Inbox not available."}

        if inbox_ids:
            count = 0
            for inbox_id in inbox_ids:
                self.state.acknowledge_inbox(inbox_id)
                count += 1
            return {"acknowledged": count, "summary": f"Acknowledged {count} notifications."}
        else:
            count = self.state.acknowledge_all_inbox()
            return {
                "acknowledged": count,
                "summary": f"Cleared all {count} notifications."
                if count > 0
                else "No notifications to clear.",
            }

    async def handle_update_working_prompt(
        self,
        title: str,
        intent: str,
        requirements: list[str] | None = None,
        constraints: list[str] | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Update the working prompt with task details.

        Args:
            title: Task title
            intent: What the user wants to achieve
            requirements: Specific requirements
            constraints: Things to avoid or constraints
            context: Additional context

        Returns:
            Confirmation with summary
        """
        if not self.prompt_manager:
            return {"error": "Prompt manager not available."}

        if not self.current_task_id:
            return {"error": "No active task."}

        await self.prompt_manager.update_working_prompt(
            task_id=self.current_task_id,
            title=title,
            intent=intent,
            requirements=requirements,
            constraints=constraints,
            context=context,
        )

        summary = self.prompt_manager.get_working_summary(self.current_task_id)

        return {"updated": True, "summary": summary}

    async def handle_freeze_prompt(self, confirm_summary: str | None = None) -> dict[str, Any]:
        """Freeze the working prompt to handoff format.

        Args:
            confirm_summary: Optional summary to confirm with user

        Returns:
            Paths to handoff files and confirmation
        """
        if not self.prompt_manager:
            return {"error": "Prompt manager not available."}

        if not self.current_task_id:
            return {"error": "No active task."}

        try:
            handoff_md_path, handoff_json_path = await self.prompt_manager.freeze_to_handoff(
                self.current_task_id
            )

            return {
                "frozen": True,
                "handoff_md_path": str(handoff_md_path),
                "handoff_json_path": str(handoff_json_path),
                "summary": f"Prompt frozen and ready for builder. Files at {handoff_md_path.parent}",
            }

        except FileNotFoundError as e:
            return {"error": str(e), "frozen": False}

    async def _auto_route(self, plan_path: Path) -> str:
        """Determine best agent based on task analysis.

        Args:
            plan_path: Path to plan file

        Returns:
            Agent name to use
        """
        async with aiofiles.open(plan_path) as f:
            plan_content = await f.read()

        plan_lower = plan_content.lower()

        # Route complex tasks to Claude Code
        complex_keywords = [
            "architecture",
            "refactor",
            "security",
            "design",
            "restructure",
            "migration",
            "overhaul",
        ]
        if any(word in plan_lower for word in complex_keywords):
            return "claude-code"

        # Large plans go to Claude Code
        if len(plan_content) > 5000:
            return "claude-code"

        # Count files mentioned
        file_refs = re.findall(r'path="([^"]+)"', plan_content)
        if len(file_refs) > 5:
            return "claude-code"

        # Default to OpenCode for simpler tasks
        return "opencode"

    async def _invoke_claude_code(self, task_id: str, plan_file: str, mode: str) -> None:
        """Invoke Claude Code with task.

        Claude Code handles its own worktree management.

        Args:
            task_id: Beads task ID
            plan_file: Path to plan file
            mode: plan (Opus) or build (Sonnet)
        """
        model = "opus" if mode == "plan" else "sonnet"

        # Claude Code handles worktree management internally
        subprocess.Popen(
            [
                "claude",
                "--model",
                model,
                "--print",
                f"Execute task from {plan_file}. Task ID: {task_id}",
            ]
        )

    def _extract_filename(self, content: str) -> str:
        """Extract filename from READY_FOR_BUILDER signal.

        Args:
            content: Message content containing signal

        Returns:
            Extracted filename
        """
        match = re.search(r"READY_FOR_BUILDER:\s*(\S+)", content)
        if match:
            return match.group(1)
        return "unknown.md"

    async def _update_memory_index(self, content: str, keywords: list[str]) -> None:
        """Update the memory keyword index.

        Args:
            content: Memory content
            keywords: Keywords to index
        """
        import yaml

        try:
            async with aiofiles.open(self._memory_index_path) as f:
                index = yaml.safe_load(await f.read()) or {}
        except FileNotFoundError:
            index = {"keywords": {}, "files": {}}

        # Add keywords
        for keyword in keywords:
            if keyword not in index.get("keywords", {}):
                index.setdefault("keywords", {})[keyword] = []
            index["keywords"][keyword].append(
                {"timestamp": datetime.utcnow().isoformat(), "preview": content[:100]}
            )

        async with aiofiles.open(self._memory_index_path, "w") as f:
            await f.write(yaml.dump(index))

    # Command classification patterns for quick_dispatch
    QUICK_QUERY_PATTERNS = [
        r"^ls\b",
        r"^tree\b",
        r"^pwd$",
        r"^cat\b",
        r"^head\b",
        r"^tail\b",
        r"^find\b.*-type",
        r"^which\b",
        r"^wc\b",
        r"^git\s+(status|log|diff|branch|show)\b",
        r"^file\b",
        r"^stat\b",
    ]

    SIMPLE_MUTATION_PATTERNS = [
        r'^mkdir\s+(-p\s+)?"?[\w./_-]+"?$',  # mkdir [-p] path (with optional quotes)
        r'^mkdir\s+-p\s+"?[\w./_-]+"?$',  # mkdir -p path explicitly
        r'^touch\s+"?[\w./_-]+"?$',  # touch path
        r"^cp\b",
        r"^mv\b",
        r"^git\s+(add|checkout|switch|branch\s+-[dD]?)\b",
    ]

    BLOCKED_PATTERNS = [
        r"\brm\b",
        r"\brmdir\b",
        r"\bsudo\b",
        r"--force",
        r"--hard",
        r"\|",  # Pipes need full review
        r"&&",  # Chained commands need full review
        r";\s*",  # Command separators need review
        r">\s*",  # Redirects need review
        r"\bchmod\b.*777",
    ]

    def _classify_command(self, operation: str, command: str) -> tuple[bool, str]:
        """Classify command as safe for quick dispatch.

        Args:
            operation: Type of operation (query or simple_mutation)
            command: The command to classify

        Returns:
            Tuple of (is_safe, reason)
        """
        # Check blocked patterns first
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, command):
                return (
                    False,
                    f"Command contains blocked pattern. Use engage_planner for this operation.",
                )

        if operation == "query":
            for pattern in self.QUICK_QUERY_PATTERNS:
                if re.match(pattern, command):
                    return True, ""
            return False, "Query pattern not recognized. Use engage_planner for safety."

        if operation == "simple_mutation":
            for pattern in self.SIMPLE_MUTATION_PATTERNS:
                if re.match(pattern, command):
                    return True, ""
            return False, "Mutation pattern not recognized. Use engage_planner for safety."

        return False, "Unknown operation type."

    async def handle_quick_dispatch(
        self, operation: str, command: str, working_dir: str | None = None
    ) -> dict[str, Any]:
        """Execute quick operations via the fastest available builder.

        Routes simple queries and mutations through OpenCode-fast for
        proper audit trails while maintaining low latency.

        Args:
            operation: Type - 'query' for read-only, 'simple_mutation' for safe writes
            command: The command to execute
            working_dir: Optional working directory (default: project root)

        Returns:
            Command output or routing instructions
        """
        # Debug: log the command being attempted
        print(f"[quick_dispatch] operation={operation}, command={repr(command)}")

        # Classify and validate the command
        is_safe, reason = self._classify_command(operation, command)
        if not is_safe:
            print(f"[quick_dispatch] REJECTED: {reason}")
            return {
                "success": False,
                "requires_full_dispatch": True,
                "reason": reason,
                "command": command,
                "hint": "Use engage_planner to properly plan and dispatch this operation.",
            }

        # Determine working directory
        cwd = working_dir
        if not cwd:
            if self.config and self.config.root_project_dir:
                cwd = self.config.root_project_dir
            else:
                cwd = str(Path.cwd())

        # Always use local subprocess for actual command execution
        # (LLM builders can't actually run shell commands, they only generate text)
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,  # Quick ops should be fast
                cwd=cwd,
            )

            # Emit event for audit trail
            if self.state:
                self.state.emit_event(
                    "QuickDispatchExecuted",
                    {
                        "command": command,
                        "operation": operation,
                        "builder": "local",
                        "success": result.returncode == 0,
                    },
                )

            if result.returncode == 0:
                output = result.stdout.strip() if result.stdout else "Done."
                print(f"[quick_dispatch] SUCCESS: {output[:100] if output else 'Done'}")
                return {
                    "success": True,
                    "output": output,
                    "command": command,
                    "working_dir": cwd,
                    "via": "local",
                }
            else:
                error = (
                    result.stderr.strip()
                    if result.stderr
                    else f"Command failed with code {result.returncode}"
                )
                print(f"[quick_dispatch] FAILED: {error}")
                return {"success": False, "error": error, "command": command, "working_dir": cwd}

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Command timed out (30s limit for quick operations)",
                "command": command,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "command": command}

    async def handle_engage_brainstormer(
        self, topic: str, context: str = "", constraints: list[str] | None = None
    ) -> dict[str, Any]:
        """Engage brainstormer subagent for free-form ideation.

        Args:
            topic: What to brainstorm or discuss
            context: Relevant context for the discussion
            constraints: Any constraints to keep in mind

        Returns:
            Brainstormer's response
        """
        message = topic
        if context:
            message = f"{topic}\n\nContext: {context}"
        if constraints:
            message += f"\n\nConstraints to consider: {', '.join(constraints)}"

        responses: list[str] = []

        async for event in self.opencode.engage_subagent("brainstormer", message):
            content = event.get("content", "")
            if event.get("type") == "message":
                responses.append(content)

        if responses:
            return {"response": responses[-1]}

        return {"response": "Let's think about this..."}

    async def handle_get_builder_plan(self, task_id: str) -> dict[str, Any]:
        """Get the plan response from a builder in plan mode.

        Args:
            task_id: Task ID to get plan for

        Returns:
            Plan content and summary
        """
        # Try to get plan from builder registry
        for name, builder in self.builders.builders.items():
            if task_id in builder.plan_sessions:
                result = await builder.get_plan_response(task_id)
                if result.get("plan"):
                    # Summarize for voice
                    plan = result["plan"]
                    summary = plan[:500] + "..." if len(plan) > 500 else plan
                    return {
                        "task_id": task_id,
                        "builder": name,
                        "plan": plan,
                        "summary": summary,
                        "awaiting_approval": True,
                    }

        # Check local state for plan file
        if self.state:
            task = self.state.get_task(task_id)
            if task and task.plan_response:
                return {
                    "task_id": task_id,
                    "plan": task.plan_response,
                    "summary": task.plan_response[:500] + "..."
                    if len(task.plan_response) > 500
                    else task.plan_response,
                    "awaiting_approval": True,
                }

        return {
            "error": f"No plan found for task {task_id}. Make sure to dispatch with mode='plan' first.",
            "task_id": task_id,
        }

    async def handle_approve_builder_plan(
        self, task_id: str, modifications: str = ""
    ) -> dict[str, Any]:
        """Approve a builder's plan and start implementation.

        Args:
            task_id: Task ID to approve
            modifications: Optional modifications before building

        Returns:
            Confirmation that building has started
        """
        # Try to approve via builder registry
        for name, builder in self.builders.builders.items():
            if task_id in builder.plan_sessions:
                result = await builder.approve_and_build(task_id, modifications)
                if result.get("building"):
                    # Update state if available
                    if self.state:
                        self.state.update_task_status(task_id, "building")

                    return {
                        "approved": True,
                        "task_id": task_id,
                        "builder": name,
                        "message": f"Building started on {name}. I'll notify you when complete.",
                    }

        return {
            "error": f"No pending plan found for task {task_id}. Get the plan first with get_builder_plan.",
            "task_id": task_id,
        }
