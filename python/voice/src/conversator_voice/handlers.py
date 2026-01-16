"""Tool handlers for Conversator - dispatches to subagents and Beads."""

import asyncio
import inspect
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles

from .builder_client import BuilderRegistry, OpenCodeBuilder
from .builder_manager import BuilderManager
from .opencode_client import OpenCodeClient
from .session_state import SessionState
from .subagent_conversation import QuestionParser, SubagentConversationState, SubagentQuestion

if TYPE_CHECKING:
    from .config import ConversatorConfig
    from .prompt_manager import PromptManager
    from .state import StateStore


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

        entries: list[tuple[str, bool]] = []
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
            if not item.is_dir() or item.name.startswith("."):
                continue

            # Hybrid discovery: include all folders, but rank marker-based projects first.
            has_marker = any((item / marker).exists() for marker in project_markers)
            entries.append((item.name, has_marker))

        # Marker-based first, then alphabetical
        entries.sort(key=lambda e: (not e[1], e[0].lower()))

        projects = [name for name, _has_marker in entries]
        marker_projects = [name for name, has_marker in entries if has_marker]

        if not projects:
            return {
                "summary": f"No projects found in {root}. You can create a new one.",
                "projects": [],
                "workspace": str(root),
            }

        preview = projects[:5]
        if len(projects) <= 5:
            summary = f"Found {len(projects)} projects: {', '.join(preview)}."
        else:
            summary = (
                f"Found {len(projects)} projects: {', '.join(preview)}, "
                f"and {len(projects) - 5} more."
            )

        return {
            "summary": summary,
            "projects": projects,
            "projects_detailed": [
                {"name": name, "has_marker": has_marker} for name, has_marker in entries
            ],
            "marker_project_count": len(marker_projects),
            "workspace": str(root),
        }

    async def handle_select_project(
        self, project_name: str, auto_start_builder: bool = True
    ) -> dict[str, Any]:
        """Select a project to work on with fuzzy matching support.

        Supports fuzzy matching - if user says "calculator app" but folder is
        "calculator", it will match. If multiple matches, returns options for
        clarification. Auto-starts builder after selection.

        Args:
            project_name: Name of the project folder to select (supports fuzzy match)
            auto_start_builder: Whether to auto-start builder after selection

        Returns:
            Confirmation with project path, or clarification request if multiple matches
        """
        try:
            from rapidfuzz import fuzz as _fuzz  # type: ignore
            from rapidfuzz import process as _process
        except Exception:
            _fuzz = None
            _process = None

        # Fallback: avoid hard failure if rapidfuzz isn't installed.
        import difflib

        def _extract_matches(query: str, choices: list[str]) -> list[tuple[str, int, int]]:
            if _process is not None and _fuzz is not None:
                extracted = _process.extract(
                    query,
                    choices,
                    scorer=_fuzz.WRatio,
                    limit=3,
                    score_cutoff=60,
                )
                results: list[tuple[str, int, int]] = []
                for idx, (name, score, choice_idx) in enumerate(extracted):
                    results.append(
                        (name, int(score), int(choice_idx) if choice_idx is not None else idx)
                    )
                results.sort(key=lambda r: r[1], reverse=True)
                return results

            close = difflib.get_close_matches(query, choices, n=3, cutoff=0.6)
            results: list[tuple[str, int, int]] = []
            for idx, name in enumerate(close):
                score = int(
                    difflib.SequenceMatcher(None, query.lower(), name.lower()).ratio() * 100
                )
                results.append((name, score, idx))
            results.sort(key=lambda r: r[1], reverse=True)
            return results

        if not self.config:
            return {"error": "Configuration not available."}

        # Get available projects
        available = await self.handle_list_projects()
        projects = available.get("projects", [])

        if not projects:
            return {"error": "No projects found in workspace."}

        project_path = Path(self.config.root_project_dir) / project_name

        # Check for exact match first
        if project_path.exists() and project_path.is_dir():
            return await self._do_select_project(project_name, project_path, auto_start_builder)

        # Normalize common conversational suffixes: "app", "project", etc.
        normalized_query = re.sub(
            r"\b(app|project|repo|repository)\b", " ", project_name, flags=re.IGNORECASE
        )
        normalized_query = re.sub(r"\s+", " ", normalized_query).strip()

        # Fuzzy match - search for similar project names
        matches = _extract_matches(normalized_query or project_name, projects)

        if not matches:
            available_preview = ", ".join(projects[:5])
            return {
                "error": f"No project matches '{project_name}'.",
                "available_projects": projects[:5],
                "say": (
                    f"I couldn't find a project matching '{project_name}'. "
                    f"Available projects are: {available_preview}."
                ),
            }

        # High confidence single match (score > 85) - auto-select
        if len(matches) == 1 or matches[0][1] > 85:
            best_match = matches[0][0]
            best_path = Path(self.config.root_project_dir) / best_match
            result = await self._do_select_project(best_match, best_path, auto_start_builder)
            result["fuzzy_matched"] = True
            result["original_query"] = project_name
            return result

        # Multiple matches with similar scores - ask for clarification
        match_names = [m[0] for m in matches]
        match_preview = ", ".join(match_names)
        return {
            "status": "needs_clarification",
            "message": f"I found multiple projects matching '{project_name}'",
            "matches": match_names,
            "say": (
                f"I found {len(match_names)} projects that could match: {match_preview}. "
                "Which one did you mean?"
            ),
        }

    async def _do_select_project(
        self, project_name: str, project_path: Path, auto_start_builder: bool = True
    ) -> dict[str, Any]:
        """Internal: Actually select the project and optionally start builder."""
        self.session_state.current_project = project_name
        self.session_state.current_project_path = project_path

        result: dict[str, Any] = {
            "project_name": project_name,
            "project_path": str(project_path),
        }

        if auto_start_builder:
            builder_result = await self.handle_start_builder()
            if builder_result.get("status") == "running":
                result["summary"] = f"Selected {project_name} and started builder. Ready to code!"
                result["builder_status"] = "running"
            else:
                builder_error = builder_result.get("error", "unknown status")
                result["summary"] = f"Selected {project_name}. Builder: {builder_error}"
                result["builder_status"] = "error"
                result["builder_error"] = builder_result.get("error")
        else:
            result["summary"] = f"Selected project: {project_name}"
            result["hint"] = "Call start_builder to launch the coding agent."

        return result

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
                "hint": "Use select_project to work on it, or choose a different name.",
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
                    "summary": (
                        f"Created project '{safe_name}' and started the builder. Ready to code!"
                    ),
                    "project_name": safe_name,
                    "project_path": str(project_path),
                    "git_initialized": init_git,
                    "builder_status": builder_result.get("status", "unknown"),
                }
            else:
                return {
                    "summary": (
                        f"Created project '{safe_name}'. Use select_project to start working on it."
                    ),
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

        full_response = responses[-1] if responses else ""

        questions = QuestionParser.parse_questions(full_response)
        if questions:
            await self._rewrite_questions_for_voice(questions)
            session_id = self.opencode.active_sessions.get("planner", "")
            self.session_state.active_subagent_conversation = SubagentConversationState(
                subagent_name="planner",
                session_id=session_id,
                questions=questions,
            )
            self.planner_session_active = True

            conv = self.session_state.active_subagent_conversation

            return {
                "status": "needs_input",
                "question_count": len(questions),
                "current_question": 1,
                "total_questions": len(questions),
                "questions": [q.text for q in questions],
                "say": self._format_question_prompt(conv, is_first=True)
                if conv
                else questions[0].text,
            }

        # No questions detected.
        self.planner_session_active = True
        return {
            "status": "needs_input",
            "response": full_response,
            "say": full_response[:500] if full_response else "Need more information.",
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
            draft = self.session_state.active_draft
            conv = self.session_state.active_subagent_conversation
            focused = self.session_state.get_focused_thread()

            if (
                (draft and draft.target_subagent == "brainstormer")
                or (conv and conv.subagent_name == "brainstormer")
                or (focused and focused.subagent == "brainstormer")
            ):
                return await self.handle_continue_brainstormer(user_response)

            return {
                "status": "error",
                "error": "Planner session is not active. Call engage_planner first.",
            }

        conv = self.session_state.active_subagent_conversation
        if conv and conv.subagent_name == "planner":
            if conv.awaiting_send_confirmation:
                return await self._handle_final_review(conv, user_response, subagent="planner")

            has_more = conv.record_answer(user_response.strip())
            if has_more:
                return {
                    "status": "needs_input",
                    "question_count": conv.total_questions,
                    "current_question": conv.current_question_number,
                    "total_questions": conv.total_questions,
                    "questions": [q.text for q in conv.questions],
                    "say": self._format_question_prompt(conv, is_first=False),
                }

            conv.start_send_confirmation()
            return {
                "status": "awaiting_confirmation",
                "answers_collected": conv.total_questions,
                "say": (
                    "I've got your answers. Want to change anything before I send them to the "
                    "planner?"
                ),
            }

        # Legacy mode: no active conversation state.
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

        # Avoid dispatching to builders while brainstorming.
        focused = self.session_state.get_focused_thread()
        if (
            focused
            and focused.subagent == "brainstormer"
            and focused.status
            in (
                "waiting_response",
                "has_response",
                "awaiting_user",
            )
        ):
            return {
                "dispatched": False,
                "error": "Brainstorm still in progress.",
                "agent": agent,
                "say": (
                    "Let's finish the brainstorm first. Say 'send to builder' when you want "
                    "to start coding."
                ),
            }

        if self.session_state.active_subagent_conversation and (
            self.session_state.active_subagent_conversation.subagent_name == "brainstormer"
        ):
            return {
                "dispatched": False,
                "error": "Brainstorm Q and A still in progress.",
                "agent": agent,
                "say": (
                    "Let's finish the brainstorm first. Say 'send to builder' when you want "
                    "to start coding."
                ),
            }

        if not self._user_intends_builder():
            return {
                "dispatched": False,
                "error": "User has not requested builder dispatch.",
                "agent": agent,
                "say": "I can send this to a builder when you explicitly say 'send to builder'.",
            }

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
                            "message": (
                                f"Sent to {agent} in plan mode. "
                                "Use get_builder_plan to review the proposal."
                            ),
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

        return {"saved": True, "message": "Got it, I'll remember that."}

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

        # Avoid freezing while we're still brainstorming.
        focused = self.session_state.get_focused_thread()
        if (
            focused
            and focused.subagent == "brainstormer"
            and focused.status
            in (
                "waiting_response",
                "has_response",
                "awaiting_user",
            )
        ):
            return {
                "frozen": False,
                "error": "Brainstorm still in progress.",
                "say": (
                    "Let's finish the brainstorm first. Tell me when you're ready to "
                    "send something to a builder."
                ),
            }

        if self.session_state.active_subagent_conversation and (
            self.session_state.active_subagent_conversation.subagent_name == "brainstormer"
        ):
            return {
                "frozen": False,
                "error": "Brainstorm Q and A still in progress.",
                "say": (
                    "Let's finish the brainstorm first. Tell me when you're ready to "
                    "send something to a builder."
                ),
            }

        if not self._user_intends_builder():
            return {
                "frozen": False,
                "error": "User has not requested builder dispatch.",
                "say": (
                    "I can freeze this into a builder handoff when you explicitly say "
                    "'send to builder'."
                ),
            }

        try:
            handoff_md_path, handoff_json_path = await self.prompt_manager.freeze_to_handoff(
                self.current_task_id
            )

            return {
                "frozen": True,
                "handoff_md_path": str(handoff_md_path),
                "handoff_json_path": str(handoff_json_path),
                "summary": (
                    f"Prompt frozen and ready for builder. Files at {handoff_md_path.parent}"
                ),
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

    def _summarize_for_voice(self, text: str, max_lines: int = 2, max_chars: int = 220) -> str:
        """Return a short, voice-friendly snippet from a longer reply."""
        if not text.strip():
            return ""

        items: list[str] = []
        in_code_block = False

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue

            if line.startswith("```"):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                continue

            line = re.sub(r"^#+\s+", "", line)
            line = re.sub(r"^[-*•]\s+", "", line)
            line = re.sub(r"^\d+\.\s+", "", line)
            line = re.sub(r"`([^`]*)`", r"\1", line)
            line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
            line = re.sub(r"\*([^*]+)\*", r"\1", line)

            items.append(line)
            if len(items) >= max_lines:
                break

        summary = " ".join(items)
        summary = re.sub(r"\s+", " ", summary).strip()
        if len(summary) > max_chars:
            summary = summary[: max_chars - 3].rstrip() + "..."
        return summary

    async def _rewrite_questions_for_voice(self, questions: list[SubagentQuestion]) -> None:
        """Rewrite questions into voice-friendly phrasing.

        This keeps the canonical question text for sending back to the subagent,
        while allowing a shorter natural phrasing for speech.
        """
        if not questions:
            return

        prompt_lines = [
            "Rewrite these questions for speaking.",
            "- Keep the meaning exactly the same.",
            "- Keep each question short and child-friendly when possible.",
            '- Return JSON exactly like: {"questions": ["...", "..."]}',
            "",
        ]
        for q in questions:
            prompt_lines.append(f"{q.index}. {q.text}")

        prompt = "\n".join(prompt_lines)

        try:
            response_text = ""
            events = self.opencode.engage_subagent("summarizer", prompt)
            if inspect.isawaitable(events):
                events = await events

            if not hasattr(events, "__aiter__"):
                return

            async for event in events:
                if event.get("type") == "message":
                    response_text = event.get("content", "")
            if not response_text.strip():
                return

            parsed: dict[str, Any] | None = None
            try:
                parsed = json.loads(response_text)
            except Exception:
                match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                    except Exception:
                        parsed = None

            spoken_questions: list[str] = []
            if parsed and isinstance(parsed.get("questions"), list):
                spoken_questions = [str(q).strip() for q in parsed["questions"]]
            else:
                # Fallback: accept newline separated output.
                spoken_questions = [
                    line.strip("- •\t ") for line in response_text.splitlines() if line.strip()
                ]

            if len(spoken_questions) < len(questions):
                return

            for idx, question in enumerate(questions):
                spoken = spoken_questions[idx]
                if spoken:
                    question.spoken_text = spoken
        except Exception:
            # Never fail the main flow due to voice rewrite.
            return

    def _is_acknowledgment(self, text: str) -> bool:
        """Return True if the user is acknowledging/confirming.

        This is used for relay UX confirmations like:
        - "Anything else to add?"
        - "Anything else before I send?"

        We keep it intentionally permissive, because voice recognition often
        produces short acknowledgements.
        """
        cleaned = text.strip().lower()
        if not cleaned:
            return True

        cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        exact = {
            "yes",
            "yeah",
            "yup",
            "yep",
            "ok",
            "okay",
            "sure",
            "done",
            "no",
            "nope",
            "send it",
            "looks good",
            "thats it",
            "nothing else",
            "all good",
            "go ahead",
        }
        if cleaned in exact:
            return True

        # Common partials: treat short affirmations as acknowledgements, but avoid
        # misclassifying longer utterances like "yes, I want to...".
        tokens = cleaned.split()
        if tokens and tokens[0] in {"yes", "yeah", "yup", "yep"}:
            # Allow things like "yes" / "yes please".
            if len(tokens) <= 2:
                return True

        if cleaned.startswith("no "):
            if any(
                phrase in cleaned
                for phrase in (
                    "thats it",
                    "thats all",
                    "nothing else",
                    "all good",
                    "thanks",
                    "thank you",
                )
            ):
                return True

        if "send" in cleaned and "it" in cleaned:
            return True
        if "looks good" in cleaned or "all good" in cleaned:
            return True
        if "thats it" in cleaned:
            return True
        if "nothing" in cleaned and "else" in cleaned:
            return True

        return False

    def _is_affirmative(self, text: str) -> bool:
        cleaned = text.strip().lower()
        cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return False

        return cleaned in {
            "yes",
            "yeah",
            "yup",
            "yep",
            "sure",
            "please",
            "ok",
            "okay",
            "lets do it",
            "let's do it",
            "change it",
            "edit",
        } or cleaned.startswith("yes")

    def _is_negative(self, text: str) -> bool:
        cleaned = text.strip().lower()
        cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return False

        return cleaned in {
            "no",
            "nope",
            "nah",
            "dont",
            "don't",
            "leave it",
            "looks good",
            "all good",
            "thats it",
            "that's it",
            "nothing else",
        } or cleaned.startswith("no")

    def _parse_question_number(self, text: str) -> int | None:
        cleaned = text.strip().lower()
        cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return None

        match = re.search(r"\b(\d+)\b", cleaned)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

        words = {
            "one": 1,
            "first": 1,
            "two": 2,
            "second": 2,
            "three": 3,
            "third": 3,
            "four": 4,
            "fourth": 4,
            "five": 5,
            "fifth": 5,
            "six": 6,
            "sixth": 6,
            "seven": 7,
            "seventh": 7,
            "eight": 8,
            "eighth": 8,
            "nine": 9,
            "ninth": 9,
            "ten": 10,
            "tenth": 10,
        }
        for token in cleaned.split():
            if token in words:
                return words[token]

        return None

    def _ordinal(self, number: int) -> str:
        ordinals = {
            1: "first",
            2: "second",
            3: "third",
            4: "fourth",
            5: "fifth",
            6: "sixth",
            7: "seventh",
            8: "eighth",
            9: "ninth",
            10: "tenth",
        }
        return ordinals.get(number, str(number))

    def _format_question_prompt(self, conv: SubagentConversationState, *, is_first: bool) -> str:
        question = conv.get_current_question_message()
        if is_first:
            return f"{conv.get_intro_message()} First question: {question}"

        ordinal = self._ordinal(conv.current_question_number)
        return f"Okay, {ordinal} question: {question}"

    async def _handle_final_review(
        self,
        conv: SubagentConversationState,
        user_response: str,
        *,
        subagent: str,
    ) -> dict[str, Any]:
        # Editing flow: choose which question to update.
        if conv.awaiting_edit_question_number:
            number = self._parse_question_number(user_response)
            if number is None or number < 1 or number > conv.total_questions:
                return {
                    "status": "awaiting_edit_question_number",
                    "say": (
                        "Which question number do you want to change? "
                        f"One through {conv.total_questions}."
                    ),
                }

            conv.pending_edit_question_number = number
            conv.awaiting_edit_question_number = False
            conv.awaiting_edit_answer = True
            return {
                "status": "awaiting_edit_answer",
                "say": f"Okay. What's the updated answer for question {number}?",
            }

        # Editing flow: receive the updated answer.
        if conv.awaiting_edit_answer:
            number = conv.pending_edit_question_number
            if number is None:
                conv.awaiting_edit_answer = False
                return {
                    "status": "awaiting_confirmation",
                    "say": f"Want to change anything before I send them to the {subagent}?",
                }

            conv.replace_answer(number, user_response.strip())
            conv.awaiting_edit_answer = False
            conv.pending_edit_question_number = None
            return {
                "status": "awaiting_confirmation",
                "say": f"Got it. Any other changes before I send them to the {subagent}?",
            }

        # Yes/no decision: edit vs send.
        if self._is_negative(user_response):
            return await self.handle_confirm_send_to_subagent("")

        if self._is_affirmative(user_response):
            conv.awaiting_edit_question_number = True
            return {
                "status": "awaiting_edit_question_number",
                "say": "Which question number do you want to change?",
            }

        return {
            "status": "awaiting_confirmation",
            "say": f"Want to change anything before I send them to the {subagent}?",
        }

    def _user_intends_builder(self) -> bool:
        """Return True if the user's last utterance explicitly asked to build/code."""
        transcript = (self.session_state.last_user_transcript or "").lower()
        transcript = re.sub(r"\s+", " ", transcript).strip()

        if not transcript:
            return False

        explicit_phrases = (
            "send to builder",
            "send this to the builder",
            "dispatch to builder",
            "start building",
            "start coding",
            "implement it",
            "code it",
            "go ahead and implement",
            "go ahead and build",
        )
        if any(p in transcript for p in explicit_phrases):
            return True

        # "builder" alone is ambiguous; require a verb.
        if "builder" in transcript and any(
            v in transcript for v in ("send", "dispatch", "start", "run")
        ):
            return True

        return False

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
                    "Command contains blocked pattern. Use engage_planner for this operation.",
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
        """Stage a brainstorm message, then confirm before sending.

        Policy:
        - Never send to subagents immediately on intent.
        - Capture user thoughts first.
        - Gemini asks for confirmation ("Anything else?" / "Want me to send?").
        - Only after confirmation (or silence auto-confirm) do we relay to OpenCode.
        """
        from .relay_draft import RelayDraft

        # Clear any Q&A flow; brainstorm uses relay draft + threads.
        self.session_state.clear_conversation()

        spoken = (self.session_state.last_user_transcript or "").strip()
        base = spoken if spoken and len(spoken) > len(topic) else topic

        # Keep draft message minimal; context/constraints are already in the conversation.
        # If you want to include them in the eventual relay, say them out loud.
        draft = RelayDraft(target_subagent="brainstormer", topic=topic)

        draft.message = base.strip() or topic.strip()

        lowered = base.lower().replace("brainstorm", "")
        tokens = re.findall(r"[a-z0-9']+", lowered)

        filler = {
            "lets",
            "let's",
            "let",
            "about",
            "the",
            "a",
            "an",
            "my",
            "our",
            "app",
            "project",
        }
        filler.update(re.findall(r"[a-z0-9']+", topic.lower()))

        meaningful = [token for token in tokens if token and token not in filler]
        has_list = base.count(",") >= 2 or "\n" in base
        has_detail = (
            (len(meaningful) >= 4 and len(base.strip()) >= 35)
            or len(base.strip()) >= 80
            or has_list
        )

        if has_detail:
            draft.stage = "awaiting_confirmation"
            self.session_state.active_draft = draft
            return {
                "status": "needs_confirmation",
                "topic": topic,
                "say": "Got it. Anything else to add before I send this to the brainstormer?",
            }

        self.session_state.active_draft = draft
        return {
            "status": "needs_detail",
            "topic": topic,
            "say": (
                "Okay. Tell me what you want to brainstorm. When you're done, I'll ask if "
                "you want me to send it."
            ),
        }

    async def handle_continue_brainstormer(self, user_response: str) -> dict[str, Any]:
        """Continue an active brainstormer session with multi-question iteration."""
        conv = self.session_state.active_subagent_conversation

        if conv is None:
            draft = self.session_state.active_draft
            if draft and draft.target_subagent == "brainstormer":
                if draft.stage == "awaiting_detail":
                    if self._is_acknowledgment(user_response):
                        message = (draft.message.strip() or draft.topic.strip()).strip()
                        self.session_state.active_draft = None
                        if not message:
                            return {
                                "status": "needs_detail",
                                "say": "What should we brainstorm about?",
                            }
                        return await self.handle_send_to_thread(
                            message=message,
                            create_new_thread=True,
                            subagent=draft.target_subagent,
                            topic=draft.topic,
                            focus=True,
                        )

                    draft.message = (
                        (draft.message + "\n" + user_response).strip()
                        if draft.message
                        else user_response.strip()
                    )
                    draft.stage = "awaiting_confirmation"
                    draft.auto_confirm_sent = False
                    return {
                        "status": "awaiting_confirmation",
                        "say": (
                            "Got it. Anything else you want to add before I send this to the "
                            "brainstormer?"
                        ),
                    }

                if draft.stage == "awaiting_confirmation":
                    if self._is_acknowledgment(user_response):
                        message = (draft.message.strip() or draft.topic.strip()).strip()
                        self.session_state.active_draft = None
                        if not message:
                            return {
                                "status": "needs_detail",
                                "say": "What should we brainstorm about?",
                            }
                        return await self.handle_send_to_thread(
                            message=message,
                            create_new_thread=True,
                            subagent=draft.target_subagent,
                            topic=draft.topic,
                            focus=True,
                        )

                    draft.message = (draft.message + "\n" + user_response).strip()
                    draft.auto_confirm_sent = False
                    return {
                        "status": "awaiting_confirmation",
                        "say": (
                            "Got it. Anything else you want to add before I send this to the "
                            "brainstormer?"
                        ),
                    }

            focused = self.session_state.get_focused_thread()
            if focused and focused.subagent == "brainstormer":
                return await self.handle_send_to_thread(
                    message=user_response,
                    thread_id=focused.thread_id,
                    focus=True,
                )

            return {
                "status": "error",
                "error": "No active brainstormer session. Call engage_brainstormer first.",
            }

        if conv.subagent_name != "brainstormer":
            return {
                "status": "error",
                "error": "Active session is not brainstormer.",
            }

        if conv.awaiting_send_confirmation:
            return await self._handle_final_review(conv, user_response, subagent="brainstormer")

        has_more = conv.record_answer(user_response.strip())
        if has_more:
            return {
                "status": "needs_input",
                "question_count": conv.total_questions,
                "current_question": conv.current_question_number,
                "total_questions": conv.total_questions,
                "questions": [q.text for q in conv.questions],
                "say": self._format_question_prompt(conv, is_first=False),
            }

        conv.start_send_confirmation()
        return {
            "status": "awaiting_confirmation",
            "answers_collected": conv.total_questions,
            "say": (
                "I've got your answers. Want to change anything before I send them to the "
                "brainstormer?"
            ),
        }

    async def handle_confirm_send_to_subagent(self, additional_context: str = "") -> dict[str, Any]:
        """Send collected answers to the active subagent as XML."""
        conv = self.session_state.active_subagent_conversation
        if not conv:
            # Fallback: some flows use threads/drafts instead of Q&A.
            draft = self.session_state.active_draft
            if draft and draft.stage == "awaiting_confirmation":
                message = (draft.message.strip() or draft.topic.strip()).strip()
                if message:
                    self.session_state.active_draft = None
                    return await self.handle_send_to_thread(
                        message=message,
                        create_new_thread=True,
                        subagent=draft.target_subagent,
                        topic=draft.topic,
                        focus=True,
                    )

            return {
                "status": "error",
                "error": "No active conversation to send. Engage a subagent first.",
                "say": (
                    "I don't have an active subagent Q and A session right now. "
                    "If you want to send a brainstorm, tell me what you want to send "
                    "and I'll relay it."
                ),
            }

        if not conv.all_answers_collected:
            return {
                "status": "error",
                "error": f"Not all questions answered yet. {conv.questions_remaining} remaining.",
            }

        # Leaving send-confirmation stage.
        conv.awaiting_send_confirmation = False
        conv.auto_confirm_sent = False

        context_parts: list[str] = []
        staged = conv.consume_send_context()
        if staged:
            context_parts.append(staged)
        if additional_context.strip():
            context_parts.append(additional_context.strip())

        merged_context = "\n".join(context_parts).strip()

        xml_payload = conv.format_answers_xml(merged_context)
        subagent = conv.subagent_name

        responses: list[str] = []

        # Prefer explicit session routing when available (threaded mode).
        if conv.session_id:
            events = self.opencode.send_to_session(conv.session_id, subagent, xml_payload)
        else:
            events = self.opencode.continue_session(subagent, xml_payload)

        async for event in events:
            content = event.get("content", "")
            if subagent == "planner" and "READY_FOR_BUILDER:" in content:
                filename = self._extract_filename(content)
                self.planner_session_active = False
                self.session_state.clear_conversation()
                return {
                    "status": "ready",
                    "plan_file": filename,
                    "say": "The plan is ready for the builder.",
                }

            if event.get("type") == "message":
                responses.append(content)

        full_response = responses[-1] if responses else ""
        questions = QuestionParser.parse_questions(full_response)
        if questions:
            await self._rewrite_questions_for_voice(questions)
            conv.reset_for_new_questions(questions)
            return {
                "status": "needs_input",
                "subagent": subagent,
                "question_count": len(questions),
                "current_question": 1,
                "total_questions": len(questions),
                "questions": [q.text for q in questions],
                "say": self._format_question_prompt(conv, is_first=True),
            }

        # No more questions - conversation complete
        self.session_state.clear_conversation()
        if subagent == "planner":
            self.planner_session_active = False

        return {
            "status": "complete",
            "response": full_response,
            "say": full_response[:500] if full_response else "Done.",
        }

    async def handle_engage_with_project(
        self,
        subagent: str,
        topic: str,
        project: str = "",
        project_hint: str = "",
        context: str = "",
    ) -> dict[str, Any]:
        """Select project (fuzzy) + engage subagent in one action."""
        project_query = project_hint or project
        if not project_query.strip():
            return {"status": "error", "error": "Missing project name."}

        project_result = await self.handle_select_project(project_query)

        if project_result.get("status") == "needs_clarification":
            return {
                **project_result,
                "say": project_result.get("say", "I found multiple matching projects."),
            }

        if project_result.get("error"):
            return {
                **project_result,
                "say": project_result.get(
                    "say", project_result.get("error", "Failed to select project.")
                ),
            }

        project_name = project_result.get("project_name", "the project")

        if subagent == "planner":
            result = await self.handle_engage_planner(topic, context)
        elif subagent == "brainstormer":
            result = await self.handle_engage_brainstormer(topic, context)
        else:
            return {"status": "error", "error": f"Unknown subagent: {subagent}"}

        # Prefix voice output.
        say = result.get("say") or result.get("summary") or ""
        if say:
            result["say"] = f"Connected to {project_name}. {say}".strip()
        else:
            result["say"] = f"Connected to {project_name}."

        return result

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
            "error": (
                f"No plan found for task {task_id}. Make sure to dispatch with mode='plan' first."
            ),
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
            "error": (
                f"No pending plan found for task {task_id}. Get the plan first with "
                "get_builder_plan."
            ),
            "task_id": task_id,
        }

    # === Threaded Subagent Sessions (multi-session relay) ===

    async def handle_start_subagent_thread(
        self,
        subagent: str,
        topic: str = "",
        focus: bool = True,
    ) -> dict[str, Any]:
        """Create a new OpenCode session for a subagent.

        Returns quickly; sending messages is done via send_to_thread.
        """
        title = f"Conversator: {subagent}"
        session_id = await self.opencode.create_session(title=title)
        thread = self.session_state.create_thread(
            subagent=subagent, topic=topic, session_id=session_id, focus=focus
        )

        return {
            "status": "started",
            "thread_id": thread.thread_id,
            "session_id": thread.opencode_session_id,
            "subagent": thread.subagent,
            "topic": thread.topic,
            "focused": self.session_state.focused_thread_id == thread.thread_id,
            "say": f"Started a new {subagent} session.".strip(),
        }

    async def handle_list_threads(self) -> dict[str, Any]:
        """List all active threads (fresh per run)."""
        threads = []
        for thread_id, thread in self.session_state.threads.items():
            threads.append(
                {
                    "thread_id": thread_id,
                    "session_id": thread.opencode_session_id,
                    "subagent": thread.subagent,
                    "topic": thread.topic,
                    "status": thread.status,
                    "focused": self.session_state.focused_thread_id == thread_id,
                }
            )

        return {
            "count": len(threads),
            "focused_thread_id": self.session_state.focused_thread_id,
            "threads": threads,
        }

    async def handle_focus_thread(self, thread_id: str) -> dict[str, Any]:
        """Switch focus to an existing thread."""
        thread = self.session_state.get_thread(thread_id)
        if not thread:
            return {"status": "error", "error": f"Unknown thread_id: {thread_id}"}

        self.session_state.focus_thread(thread_id)
        return {
            "status": "focused",
            "thread_id": thread.thread_id,
            "session_id": thread.opencode_session_id,
            "subagent": thread.subagent,
            "topic": thread.topic,
            "say": f"Switched to {thread.subagent} thread.".strip(),
        }

    async def handle_send_to_thread(
        self,
        message: str,
        thread_id: str | None = None,
        subagent: str | None = None,
        topic: str = "",
        create_new_thread: bool = False,
        focus: bool = True,
    ) -> dict[str, Any]:
        """Send a message to a specific thread (or the focused one).

        This is non-blocking: it schedules a background task and returns immediately.
        """
        thread = None
        if thread_id:
            thread = self.session_state.get_thread(thread_id)
        else:
            thread = self.session_state.get_focused_thread()

        if create_new_thread or thread is None:
            if not subagent:
                return {
                    "status": "error",
                    "error": (
                        "No thread selected. Provide subagent (and optionally topic) to "
                        "create a new thread."
                    ),
                }
            title = f"Conversator: {subagent}"
            session_id = await self.opencode.create_session(title=title)
            thread = self.session_state.create_thread(
                subagent=subagent,
                topic=topic,
                session_id=session_id,
                focus=focus,
            )

        assert thread is not None

        print(
            f"[ThreadDispatch] thread={thread.thread_id[:8]} subagent={thread.subagent} "
            f"session={thread.opencode_session_id[:8]}..."
        )

        thread.last_user_message = message
        thread.status = "waiting_response"
        thread.updated_at = datetime.utcnow()
        self.session_state.set_thread_waiting(thread.thread_id, True)

        # Waiting music policy:
        # - Tool-driven dispatch: Gemini will speak `say` ("Okay. Sending...") in the same turn.
        # - Internal dispatch (relay draft auto-send): gemini_live.py queues the same phrase.
        # Once we dispatch, it is safe to start music after the next safe point.
        self.session_state.waiting_music_preamble_queued = True
        self.session_state.waiting_music_preamble_delivered = True

        task = asyncio.create_task(self._run_thread_request(thread.thread_id, message))
        self.session_state.track_task(task)

        return {
            "status": "queued",
            "thread_id": thread.thread_id,
            "session_id": thread.opencode_session_id,
            "subagent": thread.subagent,
            "topic": thread.topic,
            "say": f"Okay. Sending that to the {thread.subagent}.",
        }

    async def _run_thread_request(self, thread_id: str, message: str) -> None:
        thread = self.session_state.get_thread(thread_id)
        if not thread:
            return

        try:
            responses: list[str] = []
            errors: list[str] = []

            async for event in self.opencode.send_to_session(
                thread.opencode_session_id, thread.subagent, message
            ):
                if event.get("type") == "message":
                    responses.append(event.get("content", ""))
                elif event.get("type") == "error":
                    errors.append(event.get("content", ""))

            if errors and not responses:
                thread.status = "error"
                thread.last_error = errors[-1]
                self.session_state.set_thread_waiting(thread.thread_id, False)
                self.session_state.enqueue_announcement(
                    f"The {thread.subagent} hit an error: {thread.last_error}",
                    kind="error",
                    thread_id=thread.thread_id,
                )
                return

            full_response = responses[-1] if responses else ""
            thread.last_response = full_response
            thread.status = "has_response"
            thread.updated_at = datetime.utcnow()

            print(
                f"[ThreadResponse] thread={thread.thread_id[:8]} subagent={thread.subagent} "
                "complete"
            )

            # Stop waiting (music will stop when no threads are waiting).
            self.session_state.set_thread_waiting(thread.thread_id, False)

            questions = QuestionParser.parse_questions(full_response)
            qcount = len(questions)

            inbox_available = self.state is not None
            active_conv = self.session_state.active_subagent_conversation
            is_focused = self.session_state.focused_thread_id == thread.thread_id
            is_only_thread = len(self.session_state.threads) == 1
            auto_relay = active_conv is None and (is_focused or is_only_thread)

            if self.state:
                from .models import InboxItem

                summary = f"{thread.subagent} replied"
                if thread.topic:
                    summary += f" about {thread.topic}"
                if qcount:
                    summary += f" ({qcount} questions)"

                self.state.add_inbox_item(
                    InboxItem(
                        summary=summary,
                        severity="info",
                        refs={
                            "thread_id": thread.thread_id,
                            "session_id": thread.opencode_session_id,
                            "subagent": thread.subagent,
                            "topic": thread.topic,
                            "question_count": qcount,
                        },
                        acknowledged_at=datetime.utcnow() if auto_relay else None,
                    )
                )

            inbox_suffix = " It's in your inbox." if inbox_available else ""

            if qcount and auto_relay:
                await self._rewrite_questions_for_voice(questions)

                # Foreground behavior: start the Q&A loop immediately.
                self.session_state.focus_thread(thread.thread_id)
                thread.status = "awaiting_user"
                thread.updated_at = datetime.utcnow()

                self.session_state.active_subagent_conversation = SubagentConversationState(
                    subagent_name=thread.subagent,
                    session_id=thread.opencode_session_id,
                    questions=questions,
                )
                conv = self.session_state.active_subagent_conversation
                announce = (
                    self._format_question_prompt(conv, is_first=True) if conv else questions[0].text
                )
            else:
                if qcount:
                    announce = f"The {thread.subagent} replied ({qcount} questions).{inbox_suffix}"
                else:
                    snippet = ""
                    if thread.subagent == "brainstormer":
                        snippet = self._summarize_for_voice(full_response)

                    if snippet:
                        if auto_relay:
                            announce = f"The {thread.subagent} replied: {snippet}."
                        else:
                            announce = f"The {thread.subagent} replied: {snippet}.{inbox_suffix}"
                    else:
                        if auto_relay:
                            announce = f"The {thread.subagent} replied."
                        else:
                            announce = f"The {thread.subagent} replied.{inbox_suffix}"

            self.session_state.enqueue_announcement(
                announce,
                kind="response_ready",
                thread_id=thread.thread_id,
            )

        except Exception as e:
            thread.status = "error"
            thread.last_error = str(e)
            self.session_state.set_thread_waiting(thread.thread_id, False)
            self.session_state.enqueue_announcement(
                f"The {thread.subagent} hit an error: {thread.last_error}",
                kind="error",
                thread_id=thread.thread_id,
            )

    async def handle_open_thread(self, thread_id: str) -> dict[str, Any]:
        """Open a thread and relay its latest response/questions."""
        thread = self.session_state.get_thread(thread_id)
        if not thread:
            return {"status": "error", "error": f"Unknown thread_id: {thread_id}"}

        self.session_state.focus_thread(thread.thread_id)

        if not thread.last_response:
            return {
                "status": "error",
                "error": "Thread has no response yet.",
                "thread_id": thread.thread_id,
            }

        questions = QuestionParser.parse_questions(thread.last_response)
        if questions:
            await self._rewrite_questions_for_voice(questions)

            thread.status = "awaiting_user"
            thread.updated_at = datetime.utcnow()

            self.session_state.active_subagent_conversation = SubagentConversationState(
                subagent_name=thread.subagent,
                session_id=thread.opencode_session_id,
                questions=questions,
            )
            conv = self.session_state.active_subagent_conversation

            return {
                "status": "needs_input",
                "thread_id": thread.thread_id,
                "subagent": thread.subagent,
                "question_count": len(questions),
                "current_question": 1,
                "total_questions": len(questions),
                "questions": [q.text for q in questions],
                "say": self._format_question_prompt(conv, is_first=True)
                if conv
                else questions[0].text,
            }

        # No questions - give a short relay summary.
        return {
            "status": "complete",
            "thread_id": thread.thread_id,
            "subagent": thread.subagent,
            "response": thread.last_response,
            "say": thread.last_response[:600],
        }
