"""Conversator configuration loader."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BuilderConfig:
    """Builder agent configuration."""

    type: str = "opencode"
    port: int = 8002
    model: str = "opencode/gemini-3-flash"
    worktree_prefix: str = ""


@dataclass
class ConversatorConfig:
    """Main configuration for Conversator."""

    root_project_dir: str = "."
    conversator_port: int = 4096

    # Per-agent models
    models: dict[str, str] = field(default_factory=lambda: {
        "planner": "opencode/gemini-3-flash",
        "context_reader": "opencode/gemini-3-flash",
        "summarizer": "opencode/gemini-3-flash",
    })

    # Builder configs
    builders: dict[str, BuilderConfig] = field(default_factory=dict)

    # Voice config
    voice_system_prompt: str = ".conversator/prompts/conversator.md"

    # OpenCode orchestration config (Layer 2)
    # Auto-start is now smart - does proper setup like scripts/start-conversator.sh
    opencode_auto_start: bool = True
    opencode_port: int = 4096  # Matches conversator.port in config.yaml
    opencode_start_timeout: float = 30.0
    opencode_config_dir: str = ".conversator/opencode"

    @classmethod
    def load(cls, config_path: str = ".conversator/config.yaml") -> "ConversatorConfig":
        """Load config from YAML file.

        Args:
            config_path: Path to config file (relative or absolute)

        Returns:
            Loaded configuration
        """
        path = Path(config_path)
        if not path.exists():
            return cls()

        with open(path) as f:
            data = yaml.safe_load(f)

        # Parse builder configs
        builders = {}
        for name, builder_data in data.get("builders", {}).items():
            if isinstance(builder_data, dict):
                builders[name] = BuilderConfig(
                    type=builder_data.get("type", "opencode"),
                    port=builder_data.get("port", 8002),
                    model=builder_data.get("model", "opencode/gemini-3-flash"),
                    worktree_prefix=builder_data.get("worktree_prefix", ""),
                )

        # Parse voice config
        voice_data = data.get("voice", {})
        voice_system_prompt = voice_data.get(
            "system_prompt", ".conversator/prompts/conversator.md"
        )

        # Parse OpenCode orchestration config from conversator section
        conversator_data = data.get("conversator", {})

        return cls(
            root_project_dir=data.get("root_project_dir", "."),
            conversator_port=conversator_data.get("port", 4096),
            models=data.get("models", {}),
            builders=builders,
            voice_system_prompt=voice_system_prompt,
            # OpenCode settings from conversator section
            opencode_auto_start=conversator_data.get("auto_start", False),
            opencode_port=conversator_data.get("port", 4096),
            opencode_start_timeout=conversator_data.get("start_timeout", 30.0),
            opencode_config_dir=conversator_data.get("opencode_config_dir", ".conversator/opencode"),
        )

    def get_model(self, agent_name: str) -> str:
        """Get model for a specific agent.

        Args:
            agent_name: Name of the agent (planner, summarizer, context_reader)

        Returns:
            Model identifier string
        """
        return self.models.get(agent_name, "opencode/gemini-3-flash")

    def get_builder(self, name: str) -> BuilderConfig | None:
        """Get builder config by name.

        Args:
            name: Builder name (e.g., opencode-fast)

        Returns:
            BuilderConfig or None if not found
        """
        return self.builders.get(name)

    def get_builder_url(self, name: str) -> str | None:
        """Get builder HTTP URL by name.

        Args:
            name: Builder name

        Returns:
            URL string or None if builder not found
        """
        builder = self.get_builder(name)
        if builder:
            return f"http://localhost:{builder.port}"
        return None
