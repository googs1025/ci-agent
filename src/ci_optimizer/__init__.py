"""CI Agent - AI-powered GitHub CI pipeline analyzer and optimizer."""
# ci_optimizer 是整个项目的顶级包，主要子包结构：
#   tui/        — 交互式终端界面（入口：tui.app.run_tui）
#   api/        — FastAPI 后端（SSE /api/chat、/api/chat/apply、/health 等接口）
#   agents/     — 分析编排层（orchestrator、skill_registry、各维度 agent）
#   report/     — 报告格式化（Markdown / JSON 输出）
#   config.py   — AgentConfig 持久化配置（~/.ci-agent/config.json）
#   prefetch.py — AnalysisContext 构建（拉取 workflow 文件、CI 数据）
#   resolver.py — GitHub remote URL 解析（owner/repo 提取）

__version__ = "0.1.0"
