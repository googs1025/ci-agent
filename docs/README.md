# ci-agent 文档索引

## 用户指南

| 文档 | 中文 | English |
|------|------|---------|
| 使用指南 | [zh](guides/zh/usage-guide.md) | [en](guides/en/usage-guide.md) |
| 部署指南 (Docker / K8s) | [zh](guides/zh/deployment.md) | [en](guides/en/deployment.md) |
| Langfuse 可观测性 | [zh](guides/zh/langfuse-setup.md) | [en](guides/en/langfuse-setup.md) |

## 架构设计

| 文档 | 说明 |
|------|------|
| [系统架构](design/architecture.md) | 整体架构、TUI/Chat API/Tools 模块、数据流设计 |
| [Skill 系统设计](design/skill-system.md) | 声明式 Skill 定义、动态发现、按需加载机制 |
| [Webhook 设计](design/webhook.md) | GitHub Webhook 实时 CI 用量追踪技术方案（草案） |
| [Failure Triage 设计](design/failure-triage.md) | 单次失败 AI 诊断：skill 契约、DB 模型、成本控制、前端 UX |

## 产品规划

| 文档 | 说明 |
|------|------|
| [Roadmap](roadmap.md) | 产品路线图与优先级 |
| [实现计划](plans/) | 各功能模块的详细实现计划 |

## 截图

界面截图存放于 [screenshots/](screenshots/)，由 Playwright 自动生成。

---

> 快速上手请直接看 [使用指南](guides/zh/usage-guide.md)。
> 开发者了解系统架构请看 [系统架构](design/architecture.md)。
