"""Analysis filter definitions for CI pipeline analysis."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class AnalysisFilters:
    """Filters to narrow down the scope of CI analysis."""

    time_range: tuple[datetime, datetime] | None = None
    workflows: list[str] | None = None  # workflow file names, e.g. ["ci.yml"]
    status: list[str] | None = None  # "success", "failure", "cancelled"
    branches: list[str] | None = None  # branch names, e.g. ["main"]

    def to_dict(self) -> dict:
        """Serialize filters to a JSON-safe dict."""
        result: dict = {}
        if self.time_range:
            result["since"] = self.time_range[0].isoformat()
            result["until"] = self.time_range[1].isoformat()
        if self.workflows:
            result["workflows"] = self.workflows
        if self.status:
            result["status"] = self.status
        if self.branches:
            result["branches"] = self.branches
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisFilters":
        """Deserialize filters from a dict."""
        time_range = None
        if "since" in data and "until" in data:
            time_range = (
                datetime.fromisoformat(data["since"]),
                datetime.fromisoformat(data["until"]),
            )
        return cls(
            time_range=time_range,
            workflows=data.get("workflows"),
            status=data.get("status"),
            branches=data.get("branches"),
        )
