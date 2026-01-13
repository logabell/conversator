"""Tests for prompt manager - working.md to handoff.md pipeline."""

import json
import tempfile
from pathlib import Path

import pytest

from conversator_voice.prompt_manager import (
    ExecutionSpec,
    PromptManager,
    WorkingPromptData,
)


class TestWorkingPromptData:
    """Tests for WorkingPromptData dataclass."""

    def test_to_markdown_empty(self):
        """Empty WorkingPromptData produces valid markdown."""
        data = WorkingPromptData()
        md = data.to_markdown()

        assert "# Untitled Task" in md
        assert "## Intent" in md
        assert "## Requirements" in md
        assert "## Constraints" in md

    def test_to_markdown_with_content(self):
        """WorkingPromptData with content renders correctly."""
        data = WorkingPromptData(
            title="Add logout button",
            intent="Allow users to log out from the header",
            requirements=["Clear session on click", "Redirect to login page"],
            constraints=["Don't modify auth service"],
            context="User is authenticated via JWT"
        )
        md = data.to_markdown()

        assert "# Add logout button" in md
        assert "Allow users to log out from the header" in md
        assert "- Clear session on click" in md
        assert "- Redirect to login page" in md
        assert "- Don't modify auth service" in md
        assert "User is authenticated via JWT" in md

    def test_from_markdown_roundtrip(self):
        """Markdown can be parsed back to WorkingPromptData."""
        original = WorkingPromptData(
            title="Test Task",
            intent="Test the roundtrip conversion",
            requirements=["Requirement A", "Requirement B"],
            constraints=["Constraint X"],
            context="Some context"
        )

        md = original.to_markdown()
        parsed = WorkingPromptData.from_markdown(md)

        assert parsed.title == original.title
        assert parsed.intent == original.intent
        assert parsed.requirements == original.requirements
        assert parsed.constraints == original.constraints
        # Context may include timestamp footer added by to_markdown()
        assert original.context in parsed.context

    def test_from_markdown_empty_sections(self):
        """Parsing handles placeholder text correctly."""
        md = """# My Task

## Intent
_Not yet defined_

## Requirements
_None specified yet_

## Constraints
_None specified yet_
"""
        data = WorkingPromptData.from_markdown(md)

        assert data.title == "My Task"
        assert data.intent == ""
        assert data.requirements == []
        assert data.constraints == []


class TestExecutionSpec:
    """Tests for ExecutionSpec dataclass."""

    def test_default_values(self):
        """ExecutionSpec has sensible defaults."""
        spec = ExecutionSpec(goal="Test goal")

        assert spec.goal == "Test goal"
        assert spec.definition_of_done == []
        assert spec.constraints == []
        assert "diff summary" in spec.required_artifacts
        assert "write_gate" in spec.gates_required

    def test_to_json(self):
        """ExecutionSpec serializes to valid JSON."""
        spec = ExecutionSpec(
            goal="Add logout button",
            definition_of_done=["Button visible in header", "Session cleared on click"],
            constraints=["No auth service changes"]
        )

        json_str = spec.to_json()
        parsed = json.loads(json_str)

        assert parsed["goal"] == "Add logout button"
        assert len(parsed["definition_of_done"]) == 2
        assert parsed["constraints"] == ["No auth service changes"]

    def test_to_dict(self):
        """ExecutionSpec converts to dictionary."""
        spec = ExecutionSpec(goal="Test")
        d = spec.to_dict()

        assert isinstance(d, dict)
        assert d["goal"] == "Test"
        assert "definition_of_done" in d
        assert "required_artifacts" in d


class TestPromptManager:
    """Tests for PromptManager class."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            yield workspace

    @pytest.fixture
    def manager(self, temp_workspace):
        """Create PromptManager with temp workspace."""
        return PromptManager(temp_workspace)

    @pytest.mark.asyncio
    async def test_init_working_prompt(self, manager):
        """init_working_prompt creates working.md file."""
        task_id = "test-task-12345678"

        path = await manager.init_working_prompt(task_id, "My Test Task")

        assert path.exists()
        assert path.name == "working.md"
        content = path.read_text()
        assert "# My Test Task" in content

    @pytest.mark.asyncio
    async def test_update_working_prompt_merges_requirements(self, manager):
        """update_working_prompt merges requirements without duplicates."""
        task_id = "merge-test-12345678"

        # Initial prompt
        await manager.init_working_prompt(task_id, "Merge Test")

        # First update
        await manager.update_working_prompt(
            task_id,
            intent="Test merging",
            requirements=["Req A", "Req B"]
        )

        # Second update with overlap
        path = await manager.update_working_prompt(
            task_id,
            requirements=["Req B", "Req C"]  # B is duplicate
        )

        content = path.read_text()
        # Should have A, B, C but B only once
        assert content.count("- Req A") == 1
        assert content.count("- Req B") == 1
        assert content.count("- Req C") == 1

    @pytest.mark.asyncio
    async def test_update_working_prompt_appends_context(self, manager):
        """update_working_prompt appends context instead of replacing."""
        task_id = "context-test-12345678"

        await manager.init_working_prompt(task_id, "Context Test")

        # First context
        await manager.update_working_prompt(task_id, context="First context")

        # Second context
        path = await manager.update_working_prompt(task_id, context="Second context")

        content = path.read_text()
        assert "First context" in content
        assert "Second context" in content

    @pytest.mark.asyncio
    async def test_freeze_to_handoff_creates_both_files(self, manager):
        """freeze_to_handoff creates handoff.md and handoff.json."""
        task_id = "freeze-test-12345678"

        # Setup working prompt
        await manager.init_working_prompt(task_id, "Freeze Test")
        await manager.update_working_prompt(
            task_id,
            intent="Test freezing to handoff format",
            requirements=["Requirement 1", "Requirement 2"],
            constraints=["Constraint 1"]
        )

        # Freeze
        md_path, json_path = await manager.freeze_to_handoff(task_id)

        # Both files exist
        assert md_path.exists()
        assert json_path.exists()
        assert md_path.name == "handoff.md"
        assert json_path.name == "handoff.json"

    @pytest.mark.asyncio
    async def test_handoff_md_has_xml_structure(self, manager):
        """handoff.md contains XML-like task structure."""
        task_id = "xml-test-12345678"

        await manager.init_working_prompt(task_id, "XML Test")
        await manager.update_working_prompt(
            task_id,
            intent="Verify XML structure",
            requirements=["Item 1", "Item 2"]
        )

        md_path, _ = await manager.freeze_to_handoff(task_id)
        content = md_path.read_text()

        assert "<task>" in content
        assert "</task>" in content
        assert "<title>XML Test</title>" in content
        assert "<goal>" in content
        assert "<definition_of_done>" in content
        assert "<item>Item 1</item>" in content
        assert "<constraints>" in content
        assert "<gates>" in content

    @pytest.mark.asyncio
    async def test_handoff_json_has_execution_spec_schema(self, manager):
        """handoff.json contains valid ExecutionSpec."""
        task_id = "json-test-12345678"

        await manager.init_working_prompt(task_id, "JSON Test")
        await manager.update_working_prompt(
            task_id,
            intent="Verify JSON schema",
            requirements=["DoD Item"]
        )

        _, json_path = await manager.freeze_to_handoff(task_id)
        content = json.loads(json_path.read_text())

        assert "goal" in content
        assert content["goal"] == "Verify JSON schema"
        assert "definition_of_done" in content
        assert "DoD Item" in content["definition_of_done"]
        assert "constraints" in content
        assert "required_artifacts" in content
        assert "gates_required" in content

    @pytest.mark.asyncio
    async def test_freeze_without_working_raises_error(self, manager):
        """freeze_to_handoff raises FileNotFoundError if no working.md."""
        with pytest.raises(FileNotFoundError):
            await manager.freeze_to_handoff("nonexistent-task")

    @pytest.mark.asyncio
    async def test_get_working_summary(self, manager):
        """get_working_summary returns voice-friendly summary."""
        task_id = "summary-test-12345678"

        await manager.init_working_prompt(task_id, "Summary Test")
        await manager.update_working_prompt(
            task_id,
            intent="Test summary generation",
            requirements=["Req 1", "Req 2", "Req 3"]
        )

        summary = manager.get_working_summary(task_id)

        assert "Summary Test" in summary
        assert "Test summary generation" in summary
        assert "3 requirements" in summary

    def test_get_working_summary_no_prompt(self, manager):
        """get_working_summary handles missing prompt gracefully."""
        summary = manager.get_working_summary("missing-task")
        assert "No working prompt" in summary

    @pytest.mark.asyncio
    async def test_handoff_includes_standard_constraints(self, manager):
        """handoff.md includes standard security constraints."""
        task_id = "constraints-test-12345678"

        await manager.init_working_prompt(task_id, "Constraints Test")
        await manager.update_working_prompt(task_id, intent="Test constraints")

        md_path, json_path = await manager.freeze_to_handoff(task_id)

        md_content = md_path.read_text()
        json_content = json.loads(json_path.read_text())

        # Standard constraints always present
        assert "Respect existing style" in md_content
        assert "Do not modify secrets" in md_content
        assert any("destructive" in c.lower() for c in json_content["constraints"])


class TestPromptDirectory:
    """Tests for prompt directory management."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / ".conversator"
            workspace.mkdir()
            yield workspace

    def test_get_prompt_dir_uses_task_prefix(self, temp_workspace):
        """Prompt directory uses first 8 chars of task ID."""
        manager = PromptManager(temp_workspace)

        task_id = "abcd1234-full-uuid-here"
        prompt_dir = manager.get_prompt_dir(task_id)

        assert prompt_dir.name == "abcd1234"
        assert prompt_dir.exists()

    def test_get_prompt_dir_creates_directory(self, temp_workspace):
        """get_prompt_dir creates directory if missing."""
        manager = PromptManager(temp_workspace)

        task_id = "newdir12-uuid"
        prompt_dir = manager.get_prompt_dir(task_id)

        assert prompt_dir.exists()
        assert prompt_dir.is_dir()
