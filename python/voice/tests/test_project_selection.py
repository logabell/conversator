import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from conversator_voice.config import ConversatorConfig
from conversator_voice.handlers import ToolHandler


@pytest.mark.asyncio
async def test_list_projects_hybrid_ranks_marker_projects_first() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Marker-based project
        demo = root / "demo"
        demo.mkdir()
        (demo / "package.json").write_text("{}")

        # Plain folder project
        calculator = root / "calculator"
        calculator.mkdir()

        # Hidden folder should be ignored
        hidden = root / ".hidden"
        hidden.mkdir()

        config = ConversatorConfig(root_project_dir=str(root))
        handler = ToolHandler(opencode=AsyncMock(), config=config)

        result = await handler.handle_list_projects()
        projects = result["projects"]

        assert "demo" in projects
        assert "calculator" in projects
        assert ".hidden" not in projects

        # Marker projects should be ranked first.
        assert projects.index("demo") < projects.index("calculator")


@pytest.mark.asyncio
async def test_select_project_fuzzy_matches_plain_folder() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "calculator").mkdir()
        (root / "demo").mkdir()

        config = ConversatorConfig(root_project_dir=str(root))
        handler = ToolHandler(opencode=AsyncMock(), config=config)

        result = await handler.handle_select_project("calculator app", auto_start_builder=False)

        assert result["project_name"] == "calculator"
        assert result.get("fuzzy_matched") is True
        assert result.get("original_query") == "calculator app"
