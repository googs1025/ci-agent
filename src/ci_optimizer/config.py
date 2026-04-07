"""User-configurable settings for the CI Agent system."""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_DIR = Path.home() / ".ci-agent"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_MODEL = "claude-sonnet-4-20250514"


@dataclass
class AgentConfig:
    """Configuration for the AI agent system."""

    # Model settings
    model: str = DEFAULT_MODEL
    fallback_model: str | None = None

    # API keys
    anthropic_api_key: str | None = None
    github_token: str | None = None

    # Agent behavior
    max_turns: int = 20

    def save(self):
        """Persist config to ~/.ci-agent/config.json."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        # Don't persist None values
        data = {k: v for k, v in data.items() if v is not None}
        CONFIG_FILE.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> "AgentConfig":
        """Load config from file, env vars, with env vars taking priority."""
        config = cls()

        # Load from config file
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                for key, value in data.items():
                    if hasattr(config, key):
                        setattr(config, key, value)
            except (json.JSONDecodeError, OSError):
                pass

        # Env vars override file config
        if env_key := os.getenv("ANTHROPIC_API_KEY"):
            config.anthropic_api_key = env_key
        if env_token := os.getenv("GITHUB_TOKEN"):
            config.github_token = env_token
        if env_model := os.getenv("CI_AGENT_MODEL"):
            config.model = env_model

        return config

    def get_sdk_env(self) -> dict[str, str]:
        """Build env dict for Claude Agent SDK."""
        env: dict[str, str] = {}
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        return env

    def to_display_dict(self) -> dict:
        """Return config as dict with sensitive values masked."""
        d = asdict(self)
        if d.get("anthropic_api_key"):
            key = d["anthropic_api_key"]
            d["anthropic_api_key"] = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
        if d.get("github_token"):
            token = d["github_token"]
            d["github_token"] = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"
        return d
