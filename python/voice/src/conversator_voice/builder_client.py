"""OpenCode builder client for task dispatch."""

import httpx
from pathlib import Path
from typing import Any


class OpenCodeBuilder:
    """Client for dispatching tasks to OpenCode builder instances."""

    def __init__(self, name: str, base_url: str, model: str):
        """Initialize builder client.

        Args:
            name: Builder name (e.g., 'opencode-fast')
            base_url: Base URL for the builder (e.g., 'http://localhost:4096')
            model: Model identifier for this builder
        """
        self.name = name
        self.base_url = base_url
        self.model = model
        self.client = httpx.AsyncClient(timeout=600)
        self.active_sessions: dict[str, str] = {}  # task_id -> session_id
        self.plan_sessions: dict[str, str] = {}  # task_id -> session_id (for plan mode)
        self.task_directories: dict[str, str] = {}  # task_id -> directory

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def health_check(self) -> bool:
        """Check if builder is responding.

        Returns:
            True if builder is healthy, False otherwise
        """
        try:
            response = await self.client.get(f"{self.base_url}/agent")
            return response.status_code == 200
        except Exception:
            return False

    async def dispatch_task(
        self, task_id: str, prompt_path: str, project_root: str | None = None
    ) -> dict[str, Any]:
        """Dispatch a task to this builder with project context.

        Args:
            task_id: Unique task identifier
            prompt_path: Path to the prompt/plan file
            project_root: Optional project directory for context

        Returns:
            Dict with session_id and dispatch status
        """
        # Read prompt content
        prompt_content = Path(prompt_path).read_text()

        # Prepend project context so builder knows where to work
        if project_root:
            context = f"""## Project Context
Working directory: {project_root}
All file operations should be relative to this directory.

---

"""
            prompt_content = context + prompt_content

        params = {"directory": project_root} if project_root else None
        if project_root:
            self.task_directories[task_id] = project_root

        # Create session
        response = await self.client.post(
            f"{self.base_url}/session",
            params=params,
            json={"title": f"Task: {task_id[:8]}"},
        )

        if response.status_code not in (200, 201):
            return {
                "dispatched": False,
                "error": f"Failed to create session: {response.status_code}",
            }

        session = response.json()
        session_id = session.get("id") or session.get("session_id")
        self.active_sessions[task_id] = session_id

        # Send the prompt asynchronously
        prompt_response = await self.client.post(
            f"{self.base_url}/session/{session_id}/prompt_async",
            params=params,
            json={"agent": "build", "parts": [{"type": "text", "text": prompt_content}]},
        )

        if prompt_response.status_code not in (200, 201, 202, 204):
            return {
                "dispatched": False,
                "session_id": session_id,
                "error": f"Failed to send prompt: {prompt_response.status_code}",
            }

        return {"dispatched": True, "session_id": session_id}

    async def get_session_status(self, task_id: str) -> str | None:
        """Get status of a builder session.

        Args:
            task_id: Task identifier to check

        Returns:
            Session status string or None if not found
        """
        session_id = self.active_sessions.get(task_id) or self.plan_sessions.get(task_id)
        if not session_id:
            return None

        try:
            response = await self.client.get(f"{self.base_url}/session/status")
            if response.status_code != 200:
                return None

            statuses = response.json()
            status = statuses.get(session_id)
            if isinstance(status, dict):
                status_type = status.get("type")
                if isinstance(status_type, str):
                    return status_type
        except Exception:
            pass
        return None

    async def get_session_messages(self, task_id: str) -> list[dict[str, Any]]:
        """Get messages from a builder session.

        Args:
            task_id: Task identifier

        Returns:
            List of message dicts
        """
        session_id = self.active_sessions.get(task_id) or self.plan_sessions.get(task_id)
        if not session_id:
            return []

        try:
            directory = self.task_directories.get(task_id)
            params = {"directory": directory} if directory else None

            # OpenCode server v1.1+: messages are listed at /session/:id/message
            response = await self.client.get(
                f"{self.base_url}/session/{session_id}/message",
                params=params,
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return []

    async def cancel_session(self, task_id: str) -> bool:
        """Cancel an active builder session.

        Args:
            task_id: Task identifier

        Returns:
            True if canceled successfully
        """
        session_id = self.active_sessions.get(task_id) or self.plan_sessions.get(task_id)
        if not session_id:
            return False

        try:
            directory = self.task_directories.get(task_id)
            params = {"directory": directory} if directory else None

            # OpenCode server v1.1+: abort a running session via /session/:id/abort
            response = await self.client.post(
                f"{self.base_url}/session/{session_id}/abort",
                params=params,
            )
            if response.status_code in (200, 204):
                self.active_sessions.pop(task_id, None)
                self.plan_sessions.pop(task_id, None)
                self.task_directories.pop(task_id, None)
                return True
        except Exception:
            pass
        return False

    async def dispatch_task_plan_mode(
        self, task_id: str, prompt_path: str, project_root: str | None = None
    ) -> dict[str, Any]:
        """Dispatch to builder using OpenCode's `plan` agent.

        Args:
            task_id: Unique task identifier
            prompt_path: Path to the prompt/plan file
            project_root: Optional project directory for context

        Returns:
            Dict with session_id and plan mode status
        """
        # Read prompt content
        prompt_content = Path(prompt_path).read_text()

        # Prepend project context
        if project_root:
            context = f"""## Project Context
Working directory: {project_root}
All file operations should be relative to this directory.

---

"""
            prompt_content = context + prompt_content

        # Use OpenCode's built-in `plan` agent for planning.

        params = {"directory": project_root} if project_root else None
        if project_root:
            self.task_directories[task_id] = project_root

        # Create session
        response = await self.client.post(
            f"{self.base_url}/session",
            params=params,
            json={"title": f"Plan: {task_id[:8]}"},
        )

        if response.status_code not in (200, 201):
            return {
                "dispatched": False,
                "error": f"Failed to create session: {response.status_code}",
            }

        session = response.json()
        session_id = session.get("id") or session.get("session_id")
        self.plan_sessions[task_id] = session_id

        # Send the plan prompt
        prompt_response = await self.client.post(
            f"{self.base_url}/session/{session_id}/prompt_async",
            params=params,
            json={"agent": "plan", "parts": [{"type": "text", "text": prompt_content}]},
        )

        if prompt_response.status_code not in (200, 201, 202, 204):
            return {
                "dispatched": False,
                "session_id": session_id,
                "error": f"Failed to send prompt: {prompt_response.status_code}",
            }

        return {
            "dispatched": True,
            "session_id": session_id,
            "mode": "plan",
            "awaiting_review": True,
        }

    async def get_plan_response(self, task_id: str) -> dict[str, Any]:
        """Retrieve the latest assistant response from the builder session."""
        session_id = self.plan_sessions.get(task_id) or self.active_sessions.get(task_id)
        if not session_id:
            return {"error": "No session found"}

        try:
            directory = self.task_directories.get(task_id)
            params = {"directory": directory} if directory else None

            # OpenCode server v1.1+: messages are listed at /session/:id/message
            response = await self.client.get(
                f"{self.base_url}/session/{session_id}/message",
                params=params,
            )
            if response.status_code != 200:
                return {"error": f"Failed to get messages: {response.status_code}"}

            messages = response.json()

            # Find the latest assistant response and extract its text parts.
            plan_content = ""
            for msg in messages:
                info = msg.get("info", msg)
                if info.get("role") != "assistant":
                    continue

                parts = msg.get("parts", [])
                content = ""
                for part in parts:
                    if isinstance(part, dict) and part.get("type") == "text":
                        content += part.get("text", "")
                if content:
                    plan_content = content

            if plan_content:
                return {
                    "plan": plan_content,
                    "session_id": session_id,
                }

            return {"error": "No plan content found in session"}

        except Exception as e:
            return {"error": str(e)}

    async def send_to_task(
        self,
        task_id: str,
        message: str,
        agent: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to an existing builder session and wait for response."""
        session_id = None
        default_agent = None

        if task_id in self.plan_sessions:
            session_id = self.plan_sessions[task_id]
            default_agent = "plan"
        elif task_id in self.active_sessions:
            session_id = self.active_sessions[task_id]
            default_agent = "build"

        if not session_id:
            return {"error": "No builder session found for task", "task_id": task_id}

        chosen_agent = agent or default_agent or "build"

        try:
            directory = self.task_directories.get(task_id)
            params = {"directory": directory} if directory else None

            response = await self.client.post(
                f"{self.base_url}/session/{session_id}/message",
                params=params,
                json={
                    "agent": chosen_agent,
                    "parts": [{"type": "text", "text": message}],
                },
            )
            if response.status_code != 200:
                return {
                    "error": f"Failed to send message: {response.status_code}",
                    "session_id": session_id,
                    "task_id": task_id,
                }

            payload = response.json()
            parts = payload.get("parts", [])
            content = ""
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    content += part.get("text", "")

            return {
                "session_id": session_id,
                "task_id": task_id,
                "agent": chosen_agent,
                "response": content,
            }

        except Exception as e:
            return {"error": str(e), "session_id": session_id, "task_id": task_id}

    async def approve_and_build(self, task_id: str, modifications: str = "") -> dict[str, Any]:
        """Exit plan mode and start building.

        Args:
            task_id: Task identifier
            modifications: Optional modifications before building

        Returns:
            Dict with building status
        """
        session_id = self.plan_sessions.get(task_id)
        if not session_id:
            return {"error": "No plan session found"}

        try:
            # Switch to OpenCode's built-in `build` agent for implementation.
            if modifications:
                approval_msg = f"implement the plan\n\nModifications:\n{modifications}"
            else:
                approval_msg = "implement the plan"

            directory = self.task_directories.get(task_id)
            params = {"directory": directory} if directory else None

            response = await self.client.post(
                f"{self.base_url}/session/{session_id}/prompt_async",
                params=params,
                json={"agent": "build", "parts": [{"type": "text", "text": approval_msg}]},
            )


            if response.status_code not in (200, 201, 202, 204):
                return {
                    "building": False,
                    "error": f"Failed to send approval: {response.status_code}",
                }

            # Move from plan_sessions to active_sessions
            self.active_sessions[task_id] = session_id
            del self.plan_sessions[task_id]

            return {"building": True, "session_id": session_id}

        except Exception as e:
            return {"error": str(e)}


class BuilderRegistry:
    """Registry of available builder instances."""

    def __init__(self):
        """Initialize empty registry."""
        self.builders: dict[str, OpenCodeBuilder] = {}

    def register(self, name: str, builder: OpenCodeBuilder) -> None:
        """Register a builder.

        Args:
            name: Builder name
            builder: Builder client instance
        """
        self.builders[name] = builder

    def get(self, name: str) -> OpenCodeBuilder | None:
        """Get a builder by name.

        Args:
            name: Builder name

        Returns:
            Builder instance or None
        """
        return self.builders.get(name)

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all builders.

        Returns:
            Dict mapping builder name to health status
        """
        results = {}
        for name, builder in self.builders.items():
            results[name] = await builder.health_check()
        return results

    async def close_all(self) -> None:
        """Close all builder clients."""
        for builder in self.builders.values():
            await builder.close()

    def __iter__(self):
        """Iterate over builders."""
        return iter(self.builders.values())

    def __len__(self) -> int:
        """Get number of registered builders."""
        return len(self.builders)
