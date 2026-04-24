"""Rich-based stream stats tracker for the TUI."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console


@dataclass
class SessionStats:
    """Accumulated stats for the current session."""

    total_cost_usd: float = 0.0
    query_count: int = 0


@dataclass
class StreamRenderer:
    """Tracks session stats and provides a print_stats helper."""

    console: Console = field(default_factory=Console)
    stats: SessionStats = field(default_factory=SessionStats)

    def print_stats(self) -> None:
        """Print accumulated session stats."""
        self.console.print()
        self.console.print("[bold]Session Stats[/bold]")
        self.console.print(f"  查询次数: {self.stats.query_count}")
        self.console.print(f"  总花费:   ${self.stats.total_cost_usd:.4f}")
