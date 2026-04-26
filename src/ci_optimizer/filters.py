"""Analysis filter definitions for CI pipeline analysis."""
# 架构角色：数据过滤层的值对象（Value Object），描述"本次分析的范围"。
# 核心职责：以 dataclass 封装时间范围、workflow 文件名、运行状态、分支等
#           过滤条件，并提供与字典的互转方法，供 API 层和 CLI 层传递。
# 关联模块：由 cli.py 从命令行参数构建，传入 prefetch.prepare_context()
#           以缩小 GitHub API 查询范围；API 层通过 from_dict/to_dict 做序列化。

from dataclasses import dataclass
from datetime import datetime


@dataclass
class AnalysisFilters:
    """Filters to narrow down the scope of CI analysis.

    所有字段均为可选（None 表示不过滤），调用方只需填写关心的维度。
    None 字段在序列化时不写入 dict，保持传输结构精简。
    """

    time_range: tuple[datetime, datetime] | None = None
    workflows: list[str] | None = None  # workflow file names, e.g. ["ci.yml"]
    status: list[str] | None = None  # "success", "failure", "cancelled"
    branches: list[str] | None = None  # branch names, e.g. ["main"]

    def to_dict(self) -> dict:
        """Serialize filters to a JSON-safe dict.

        时间范围转为 ISO 8601 字符串，方便跨进程传递和 JSON 存储。
        """
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
        """Deserialize filters from a dict.

        to_dict() 的逆操作，用于从 API 请求体或缓存中还原过滤条件。
        """
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
