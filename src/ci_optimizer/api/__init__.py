# ci_optimizer.api 包
# 本包是 CI Agent 的 HTTP API 层，包含以下模块：
#   app.py      — FastAPI 应用实例，挂载所有路由，配置 CORS 和日志
#   routes.py   — 分析、报告、skill 管理、配置等 REST 端点（/api 前缀）
#   chat.py     — 流式聊天端点（SSE），核心是多轮 tool-use agentic loop
#   tools.py    — chat agent 可调用的工具定义与执行器（含路径沙箱和命令白名单）
#   auth.py     — API Key Bearer token 鉴权依赖注入
#   diagnose.py — CI 失败诊断端点，三级缓存策略 + failure_triage skill 调用
#   schemas.py  — 所有请求/响应的 Pydantic 数据模型
#   webhooks.py — GitHub webhook 处理（workflow_run 事件 → 分析 + 自动诊断）
