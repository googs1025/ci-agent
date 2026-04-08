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

    # Provider: "anthropic" or "openai"
    provider: str = "anthropic"

    # Model settings
    model: str = DEFAULT_MODEL
    fallback_model: str | None = None

    # API keys (used based on provider)
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    github_token: str | None = None

    # Custom API base URL (for OpenAI-compatible endpoints)
    base_url: str | None = None

    # Agent behavior
    max_turns: int = 20
    language: str = "en"  # "en" or "zh"

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
        if env_lang := os.getenv("CI_AGENT_LANGUAGE"):
            config.language = env_lang
        if env_provider := os.getenv("CI_AGENT_PROVIDER"):
            config.provider = env_provider
        if env_base_url := os.getenv("CI_AGENT_BASE_URL"):
            config.base_url = env_base_url
        if env_openai_key := os.getenv("OPENAI_API_KEY"):
            config.openai_api_key = env_openai_key

        return config

    def get_sdk_env(self) -> dict[str, str]:
        """Build env dict for Claude Agent SDK."""
        env: dict[str, str] = {}
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        return env

    def get_api_key(self) -> str | None:
        """Get the API key for the configured provider."""
        if self.provider == "openai":
            return self.openai_api_key
        return self.anthropic_api_key

    def to_display_dict(self) -> dict:
        """Return config as dict with sensitive values masked."""
        d = asdict(self)
        for key_field in ("anthropic_api_key", "openai_api_key", "github_token"):
            if d.get(key_field):
                val = d[key_field]
                d[key_field] = f"{val[:8]}...{val[-4:]}" if len(val) > 12 else "***"
        return d
