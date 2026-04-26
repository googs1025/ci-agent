"""ci_optimizer.agents — agents 层包入口。

本包包含 CI 分析系统的所有 agent 相关模块：

  orchestrator    : 顶层调度器，将分析请求路由到 Anthropic 或 OpenAI 引擎
  skill_registry  : 技能注册与管理，从 SKILL.md 文件加载 specialist 定义
  anthropic_engine: 基于 Claude Agent SDK 的并行多专家执行引擎
  openai_engine   : 基于 OpenAI Chat Completions API 的两阶段执行引擎
  failure_triage  : 独立的 CI 故障诊断技能执行器（standalone skill）
  prompts         : 共享的语言指令和输出格式常量
  skill_importer  : 从外部系统（Claude Code、OpenCode、GitHub）导入技能
  tracing         : Langfuse 可观测性集成（可选，未配置时自动禁用）
"""
