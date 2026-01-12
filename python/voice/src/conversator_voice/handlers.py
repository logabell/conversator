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

if TYPE_CHECKING:
    from .state import StateStore
    from .prompt_manager import PromptManager


class ToolHandler:
    """Handles tool calls from Gemini Live, dispatching to subagents and Beads."""

    def __init__(
        self,
        opencode: OpenCodeClient,
        state: "StateStore | None" = None,
        prompt_manager: "PromptManager | None" = None,
        current_task_id: str | None = None
    ):
        """Initialize tool handler.

        Args:
            opencode: OpenCode client for subagent communication
            state: Optional state store for task/inbox queries
            prompt_manager: Optional prompt manager for working/handoff prompts
            current_task_id: Optional current task ID for prompt operations
        """
        self.opencode = opencode
        self.state = state
        self.prompt_manager = prompt_manager
        self.current_task_id = current_task_id
        self.planner_session_active = False
        self._memory_index_path = Path(".conversator/memory/index.yaml")
        self._atomic_memory_path = Path(".conversator/memory/atomic.jsonl")

    async def handle_engage_planner(
        self,
        task_description: str,
        context: str = "",
        urgency: str = "normal"
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
                    "summary": responses[-1] if responses else "Plan ready"
                }

        # Planner is asking questions - keep session active
        self.planner_session_active = True
        return {
            "status": "needs_input",
            "questions": responses[-1] if responses else "Need more information"
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
                return {"status": "needs_input", "questions": content}

        return {"status": "error", "message": "No response from planner"}

    async def handle_lookup_context(
        self,
        query: str,
        scope: str = "both"
    ) -> dict[str, Any]:
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
                {
                    "task_id": t.task_id[:8],
                    "title": t.title,
                    "status": t.status
                }
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
                ["bd", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5
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
        parallel_with: str | None = None
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

        # Create Beads task with agent assignment
        # Beads handles task queue, agents handle their own worktrees
        cmd = [
            "bd", "create",
            f"--file={plan_path}",
            f"--assign={agent}",
            f"--meta=mode:{mode}"
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                return {
                    "error": f"Failed to create task: {result.stderr}",
                    "dispatched": False
                }

            task_id = result.stdout.strip()

            # Move plan to active
            active_path = Path(f".conversator/plans/active/{plan_path.name}")
            plan_path.rename(active_path)

            # Notify agent based on type
            if agent == "claude-code":
                await self._invoke_claude_code(task_id, str(active_path), mode)

            # Update status cache
            await self.opencode.update_status(agent, {
                "task_id": task_id,
                "status": "dispatched",
                "plan_file": str(active_path),
                "mode": mode
            })

            return {
                "dispatched": True,
                "task_id": task_id,
                "agent": agent,
                "mode": mode,
                "message": f"Sent to {agent}: {plan_path.name}"
            }

        except subprocess.TimeoutExpired:
            return {"error": "Beads command timed out", "dispatched": False}
        except FileNotFoundError:
            return {"error": "Beads (bd) not installed", "dispatched": False}

    async def handle_add_to_memory(
        self,
        content: str,
        keywords: list[str] | None = None,
        importance: str = "normal"
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
            "importance": importance
        }

        # Append to atomic memory
        async with aiofiles.open(self._atomic_memory_path, "a") as f:
            await f.write(json.dumps(memory_entry) + "\n")

        # Update keyword index
        await self._update_memory_index(content, keywords or [])

        return {
            "saved": True,
            "message": f"Got it, I'll remember that."
        }

    async def handle_cancel_task(
        self,
        task_id: str,
        reason: str = ""
    ) -> dict[str, Any]:
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

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                return {"canceled": True, "task_id": task_id}
            else:
                return {"canceled": False, "error": result.stderr}

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return {"canceled": False, "error": str(e)}

    async def handle_check_inbox(
        self,
        include_read: bool = False
    ) -> dict[str, Any]:
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
                "count": 0
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
                {
                    "inbox_id": i.inbox_id,
                    "severity": i.severity,
                    "summary": i.summary
                }
                for i in items[:5]  # Limit for voice
            ]
        }

    async def handle_acknowledge_inbox(
        self,
        inbox_ids: list[str] | None = None
    ) -> dict[str, Any]:
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
            return {
                "acknowledged": count,
                "summary": f"Acknowledged {count} notifications."
            }
        else:
            count = self.state.acknowledge_all_inbox()
            return {
                "acknowledged": count,
                "summary": f"Cleared all {count} notifications." if count > 0 else "No notifications to clear."
            }

    async def handle_update_working_prompt(
        self,
        title: str,
        intent: str,
        requirements: list[str] | None = None,
        constraints: list[str] | None = None,
        context: str | None = None
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
            context=context
        )

        summary = self.prompt_manager.get_working_summary(self.current_task_id)

        return {
            "updated": True,
            "summary": summary
        }

    async def handle_freeze_prompt(
        self,
        confirm_summary: str | None = None
    ) -> dict[str, Any]:
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
                "summary": f"Prompt frozen and ready for builder. Files at {handoff_md_path.parent}"
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
            "architecture", "refactor", "security", "design",
            "restructure", "migration", "overhaul"
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

        # Default to fast OpenCode for simpler tasks
        return "opencode-fast"

    async def _invoke_claude_code(
        self,
        task_id: str,
        plan_file: str,
        mode: str
    ) -> None:
        """Invoke Claude Code with task.

        Claude Code handles its own worktree management.

        Args:
            task_id: Beads task ID
            plan_file: Path to plan file
            mode: plan (Opus) or build (Sonnet)
        """
        model = "opus" if mode == "plan" else "sonnet"

        # Claude Code handles worktree management internally
        subprocess.Popen([
            "claude",
            "--model", model,
            "--print", f"Execute task from {plan_file}. Task ID: {task_id}"
        ])

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

    async def _update_memory_index(
        self,
        content: str,
        keywords: list[str]
    ) -> None:
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
            index["keywords"][keyword].append({
                "timestamp": datetime.utcnow().isoformat(),
                "preview": content[:100]
            })

        async with aiofiles.open(self._memory_index_path, "w") as f:
            await f.write(yaml.dump(index))
