"""Prompt management for Conversator - working.md to handoff.md pipeline."""

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import StateStore


@dataclass
class ExecutionSpec:
    """Structured specification for builder handoff."""

    goal: str
    definition_of_done: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    repo_targets: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=lambda: [
        "diff summary",
        "test output"
    ])
    gates_required: list[str] = field(default_factory=lambda: [
        "write_gate",
        "run_gate"
    ])
    budgets: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class WorkingPromptData:
    """In-memory representation of working.md content."""

    title: str = "Untitled Task"
    intent: str = ""
    requirements: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    context: str = ""
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_markdown(self) -> str:
        """Convert to markdown format."""
        lines = [f"# {self.title}", ""]

        lines.append("## Intent")
        lines.append(self.intent if self.intent else "_Not yet defined_")
        lines.append("")

        lines.append("## Requirements")
        if self.requirements:
            for req in self.requirements:
                lines.append(f"- {req}")
        else:
            lines.append("_None specified yet_")
        lines.append("")

        lines.append("## Constraints")
        if self.constraints:
            for con in self.constraints:
                lines.append(f"- {con}")
        else:
            lines.append("_None specified yet_")
        lines.append("")

        if self.context:
            lines.append("## Context")
            lines.append(self.context)
            lines.append("")

        lines.append(f"_Last updated: {self.updated_at.isoformat()}_")

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, content: str) -> "WorkingPromptData":
        """Parse markdown content into WorkingPromptData."""
        data = cls()

        # Extract title from first heading
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if title_match:
            data.title = title_match.group(1).strip()

        # Extract sections
        sections = re.split(r'^##\s+', content, flags=re.MULTILINE)

        for section in sections[1:]:  # Skip content before first ##
            lines = section.strip().split('\n')
            header = lines[0].strip().lower()
            body = '\n'.join(lines[1:]).strip()

            if header == "intent":
                if body and not body.startswith("_"):
                    data.intent = body
            elif header == "requirements":
                data.requirements = cls._extract_list_items(body)
            elif header == "constraints":
                data.constraints = cls._extract_list_items(body)
            elif header == "context":
                if body and not body.startswith("_"):
                    data.context = body

        return data

    @staticmethod
    def _extract_list_items(body: str) -> list[str]:
        """Extract list items from markdown body."""
        items = []
        for line in body.split('\n'):
            line = line.strip()
            if line.startswith('- ') and not line.startswith('_'):
                items.append(line[2:].strip())
        return items


class PromptManager:
    """Manages working.md and handoff.md files for tasks."""

    def __init__(self, workspace_path: Path, state: "StateStore | None" = None):
        """Initialize prompt manager.

        Args:
            workspace_path: Path to .conversator workspace
            state: Optional state store for event emission
        """
        self.workspace = workspace_path
        self.state = state
        self._current_task_id: str | None = None
        self._working_data: WorkingPromptData | None = None

    def get_prompt_dir(self, task_id: str) -> Path:
        """Get or create prompt directory for a task.

        Args:
            task_id: Task ID (uses first 8 chars as directory name)

        Returns:
            Path to the prompt directory
        """
        prompt_dir = self.workspace / "prompts" / task_id[:8]
        prompt_dir.mkdir(parents=True, exist_ok=True)
        return prompt_dir

    def get_working_path(self, task_id: str) -> Path:
        """Get path to working.md for a task."""
        return self.get_prompt_dir(task_id) / "working.md"

    def get_handoff_md_path(self, task_id: str) -> Path:
        """Get path to handoff.md for a task."""
        return self.get_prompt_dir(task_id) / "handoff.md"

    def get_handoff_json_path(self, task_id: str) -> Path:
        """Get path to handoff.json for a task."""
        return self.get_prompt_dir(task_id) / "handoff.json"

    async def init_working_prompt(self, task_id: str, title: str = "Untitled Task") -> Path:
        """Create initial working.md for a task.

        Args:
            task_id: Task ID
            title: Initial task title

        Returns:
            Path to created working.md
        """
        self._current_task_id = task_id
        self._working_data = WorkingPromptData(title=title)

        path = self.get_working_path(task_id)
        path.write_text(self._working_data.to_markdown())

        return path

    async def update_working_prompt(
        self,
        task_id: str,
        title: str | None = None,
        intent: str | None = None,
        requirements: list[str] | None = None,
        constraints: list[str] | None = None,
        context: str | None = None
    ) -> Path:
        """Update working.md with new details.

        Args:
            task_id: Task ID
            title: New title (if provided)
            intent: New intent (if provided)
            requirements: Requirements to add/replace
            constraints: Constraints to add/replace
            context: Additional context

        Returns:
            Path to updated working.md
        """
        path = self.get_working_path(task_id)

        # Load existing or create new
        if self._current_task_id == task_id and self._working_data:
            data = self._working_data
        elif path.exists():
            data = WorkingPromptData.from_markdown(path.read_text())
        else:
            data = WorkingPromptData()

        # Update fields
        if title:
            data.title = title
        if intent:
            data.intent = intent
        if requirements:
            # Merge requirements (avoid duplicates)
            existing = set(data.requirements)
            for req in requirements:
                if req not in existing:
                    data.requirements.append(req)
        if constraints:
            # Merge constraints
            existing = set(data.constraints)
            for con in constraints:
                if con not in existing:
                    data.constraints.append(con)
        if context:
            # Append context
            if data.context:
                data.context += f"\n\n{context}"
            else:
                data.context = context

        data.updated_at = datetime.utcnow()

        # Save
        path.write_text(data.to_markdown())
        self._current_task_id = task_id
        self._working_data = data

        # Emit event if state is available
        if self.state:
            self.state.update_task_status(
                task_id,
                "WorkingPromptUpdated",
                {"path": str(path), "summary": data.title}
            )

        return path

    async def freeze_to_handoff(self, task_id: str) -> tuple[Path, Path]:
        """Freeze working.md to handoff.md and handoff.json.

        Args:
            task_id: Task ID to freeze

        Returns:
            Tuple of (handoff_md_path, handoff_json_path)
        """
        working_path = self.get_working_path(task_id)

        if not working_path.exists():
            raise FileNotFoundError(f"No working.md found for task {task_id}")

        # Load working data
        data = WorkingPromptData.from_markdown(working_path.read_text())

        # Generate handoff.md (XML-like structure)
        handoff_md = self._format_handoff_md(data, task_id)
        handoff_md_path = self.get_handoff_md_path(task_id)
        handoff_md_path.write_text(handoff_md)

        # Generate handoff.json (ExecutionSpec)
        spec = self._extract_execution_spec(data)
        handoff_json_path = self.get_handoff_json_path(task_id)
        handoff_json_path.write_text(spec.to_json())

        # Emit event if state is available
        if self.state:
            self.state.update_task_status(
                task_id,
                "HandoffFrozen",
                {
                    "handoff_md_path": str(handoff_md_path),
                    "handoff_json_path": str(handoff_json_path)
                }
            )

        return handoff_md_path, handoff_json_path

    def _format_handoff_md(self, data: WorkingPromptData, task_id: str) -> str:
        """Convert WorkingPromptData to XML-like handoff format.

        Args:
            data: Working prompt data
            task_id: Task ID for context pointers

        Returns:
            Handoff markdown content
        """
        lines = ["<task>", f"  <title>{data.title}</title>", ""]

        lines.append("  <goal>")
        lines.append(f"    {data.intent}")
        lines.append("  </goal>")
        lines.append("")

        lines.append("  <definition_of_done>")
        for req in data.requirements:
            lines.append(f"    <item>{req}</item>")
        lines.append("  </definition_of_done>")
        lines.append("")

        lines.append("  <constraints>")
        # Always include standard constraints
        standard_constraints = [
            "Respect existing style and architecture.",
            "Do not modify secrets (.env, tokens). Redact if encountered.",
            "Ask before running commands or making destructive changes."
        ]
        for con in standard_constraints + data.constraints:
            lines.append(f"    <item>{con}</item>")
        lines.append("  </constraints>")
        lines.append("")

        lines.append("  <expected_artifacts>")
        lines.append("    <item>diff summary</item>")
        lines.append("    <item>test output</item>")
        lines.append("  </expected_artifacts>")
        lines.append("")

        lines.append("  <gates>")
        lines.append("    <write_gate>true</write_gate>")
        lines.append("    <run_gate>true</run_gate>")
        lines.append("    <destructive_gate>true</destructive_gate>")
        lines.append("  </gates>")
        lines.append("")

        lines.append("  <context_pointers>")
        lines.append(f'    <artifact path=".conversator/prompts/{task_id[:8]}/handoff.json"/>')
        lines.append("  </context_pointers>")

        lines.append("</task>")

        return "\n".join(lines)

    def _extract_execution_spec(self, data: WorkingPromptData) -> ExecutionSpec:
        """Extract ExecutionSpec from WorkingPromptData.

        Args:
            data: Working prompt data

        Returns:
            ExecutionSpec for JSON serialization
        """
        return ExecutionSpec(
            goal=data.intent,
            definition_of_done=data.requirements.copy(),
            constraints=[
                "Respect existing style and architecture.",
                "Do not modify secrets (.env, tokens). Redact if encountered.",
                "Ask before running commands or making destructive changes."
            ] + data.constraints
        )

    def get_working_summary(self, task_id: str) -> str:
        """Get a voice-friendly summary of the current working prompt.

        Args:
            task_id: Task ID

        Returns:
            Summary string
        """
        path = self.get_working_path(task_id)

        if not path.exists():
            return "No working prompt yet."

        data = WorkingPromptData.from_markdown(path.read_text())

        parts = [f"Task: {data.title}."]
        if data.intent:
            parts.append(f"Goal: {data.intent}")
        if data.requirements:
            parts.append(f"{len(data.requirements)} requirements defined.")
        if data.constraints:
            parts.append(f"{len(data.constraints)} constraints.")

        return " ".join(parts)
