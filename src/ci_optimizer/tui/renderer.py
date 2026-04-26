"""Rich-based stream stats tracker for the TUI."""
# 架构角色：会话级统计数据的持有者和展示模块，是 app.py 与 Rich Console 之间的薄包装层。
# 核心职责：
#   1. 通过 SessionStats 跨轮次累积 token 花费和查询次数
#   2. 提供 print_stats() 供 /cost 命令调用
# 与其他模块的关系：
#   - app.py 在每次 SSE done 事件后更新 renderer.stats，并将 renderer 作为共享引用传递
#   - commands.py 的 _cmd_cost() 通过 renderer.print_stats() 读取统计数据

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console


@dataclass
class SessionStats:
    """单次 TUI 会话的累计统计：总花费（USD）和已执行的查询轮次。"""

    total_cost_usd: float = 0.0
    query_count: int = 0


@dataclass
class StreamRenderer:
    """持有 Rich Console 和 SessionStats，作为 app.py 中跨函数共享的渲染上下文对象。
    设计为 dataclass 而非普通类，方便在函数间以单一引用传递，避免 console/stats 各自散落。
    """

    console: Console = field(default_factory=Console)
    stats: SessionStats = field(default_factory=SessionStats)

    def print_stats(self) -> None:
        """Print accumulated session stats."""
        self.console.print()
        self.console.print("[bold]Session Stats[/bold]")
        self.console.print(f"  查询次数: {self.stats.query_count}")
        self.console.print(f"  总花费:   ${self.stats.total_cost_usd:.4f}")
