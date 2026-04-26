"""Interactive TUI for ci-agent."""
# tui 包的公共入口，对外只暴露包名，具体功能通过子模块访问：
#   tui.app       — TUI 总入口（run_tui）
#   tui.commands  — 斜杠命令解析
#   tui.panels    — 写入确认面板
#   tui.renderer  — 会话统计渲染
#   tui.repl      — PromptSession 配置
#   tui.context   — 仓库检测与确认
#   tui.setup     — 首次配置向导
