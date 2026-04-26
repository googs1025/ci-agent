"""User-configurable settings for the CI Agent system."""
# 架构角色：配置层的核心文件，定义整个 CI Agent 系统的用户可配置参数。
# 核心职责：通过 AgentConfig dataclass 集中管理所有运行时配置项，
#           支持从 JSON 文件和环境变量两路加载，并以环境变量优先。
# 关联模块：被 cli.py 用于初始化运行参数，被 tui/ 用于展示和修改配置，
#           被 diagnose/ 用于读取故障诊断相关的模型和预算配置。

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".ci-agent"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_MODEL = "claude-sonnet-4-20250514"


@dataclass
class AgentConfig:
    """Configuration for the AI agent system.

    统一持有所有运行时配置，包括 LLM provider 选择、API 密钥、
    Agent 行为参数（max_turns、language），以及故障诊断（diagnose_*）的
    模型、采样率、每日费用上限等成本控制字段。
    """

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

    # Anthropic API base URL (for proxies / custom endpoints)
    anthropic_base_url: str | None = None

    # Agent behavior
    max_turns: int = 20
    language: str = "en"  # "en" or "zh"

    # Failure triage (single-run diagnosis) — issue #35
    diagnose_default_model: str = "claude-haiku-4-5-20251001"
    diagnose_deep_model: str = "claude-sonnet-4-20250514"
    # v1 cost controls
    diagnose_auto_on_webhook: bool = True
    diagnose_sample_rate: float = 1.0  # 0.0–1.0 — fraction of failing runs to auto-diagnose
    diagnose_budget_usd_day: float = 1.0  # hard ceiling on 24h auto-diagnosis spend
    diagnose_signature_ttl_hours: int = 24  # signature dedup window

    def save(self):
        """Persist config to ~/.ci-agent/config.json."""
        # 将当前配置序列化到用户主目录，供下次启动时复用。
        # None 值不写入文件，避免覆盖掉未来版本的字段默认值。
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        # Don't persist None values
        data = {k: v for k, v in data.items() if v is not None}
        CONFIG_FILE.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> "AgentConfig":
        """Load config from file, env vars, with env vars taking priority.

        加载优先级：默认值 < JSON 文件 < 环境变量。
        环境变量始终覆盖文件配置，方便 CI 场景下无感注入密钥。
        """
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
        if env_anthropic_base := os.getenv("ANTHROPIC_BASE_URL"):
            config.anthropic_base_url = env_anthropic_base
        if env_openai_key := os.getenv("OPENAI_API_KEY"):
            config.openai_api_key = env_openai_key
        if env_diag_default := os.getenv("DIAGNOSE_DEFAULT_MODEL"):
            config.diagnose_default_model = env_diag_default
        if env_diag_deep := os.getenv("DIAGNOSE_DEEP_MODEL"):
            config.diagnose_deep_model = env_diag_deep
        if env_auto := os.getenv("DIAGNOSE_AUTO_ON_WEBHOOK"):
            config.diagnose_auto_on_webhook = env_auto.lower() in ("1", "true", "yes")
        if env_sample := os.getenv("DIAGNOSE_SAMPLE_RATE"):
            try:
                # 强制钳位到 [0.0, 1.0]，防止调用方传入非法比率导致全量诊断失控
                config.diagnose_sample_rate = max(0.0, min(1.0, float(env_sample)))
            except ValueError:
                pass
        if env_budget := os.getenv("DIAGNOSE_BUDGET_USD_DAY"):
            try:
                config.diagnose_budget_usd_day = max(0.0, float(env_budget))
            except ValueError:
                pass
        if env_sig_ttl := os.getenv("DIAGNOSE_SIGNATURE_TTL_HOURS"):
            try:
                config.diagnose_signature_ttl_hours = max(1, int(env_sig_ttl))
            except ValueError:
                pass

        return config

    def get_sdk_env(self) -> dict[str, str]:
        """Build env dict for Claude Agent SDK.

        将配置中的 Anthropic 密钥和自定义 base URL 转成环境变量字典，
        供底层 SDK 进程透传使用，避免全局污染 os.environ。
        """
        env: dict[str, str] = {}
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        if self.anthropic_base_url:
            env["ANTHROPIC_BASE_URL"] = self.anthropic_base_url
        return env

    def __post_init__(self):
        # dataclass 初始化后的自检：将非法 provider 静默回退到默认值，
        # 而非抛出异常，保持配置加载的容错性。
        if self.provider not in ("anthropic", "openai"):
            self.provider = "anthropic"
        if self.max_turns < 1:
            self.max_turns = 20

    def get_api_key(self) -> str | None:
        """Get the API key for the configured provider.

        根据当前 provider 返回对应的 API key，调用方无需关心 provider 类型。
        """
        if self.provider == "openai":
            return self.openai_api_key
        return self.anthropic_api_key

    def to_display_dict(self) -> dict:
        """Return config as dict with sensitive values masked.

        用于 TUI/CLI 展示配置时对密钥做脱敏处理，只显示前 8 位和后 4 位。
        """
        d = asdict(self)
        for key_field in ("anthropic_api_key", "openai_api_key", "github_token"):
            if d.get(key_field):
                val = d[key_field]
                d[key_field] = f"{val[:8]}...{val[-4:]}" if len(val) > 12 else "***"
        return d
