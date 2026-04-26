"""GitHub REST API client for fetching CI run data.

架构角色：外部数据源适配层，将 GitHub Actions REST API 封装为可复用的异步客户端。
核心职责：获取 workflow runs、jobs、日志（整包 zip 和单 job 纯文本两种形式），
以及仓库元数据、workflow 列表、运行时间和 Action ref 解析。
与其他模块的关系：被 AI 技能（skill_runner）和 Webhook 处理器调用以拉取原始 CI 数据；
AnalysisFilters 在此处被转换为 GitHub API 参数或客户端侧过滤条件。
"""

import asyncio
import io
import os
import zipfile
from datetime import datetime, timezone

import httpx

from ci_optimizer.filters import AnalysisFilters

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """封装 GitHub Actions REST API 的异步客户端，支持 Token 认证和限流自动重试。"""

    def __init__(self, token: str | None = None, config: "AgentConfig | None" = None):
        if config and config.github_token:
            self.token = config.github_token
        else:
            self.token = token or os.getenv("GITHUB_TOKEN")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """懒加载 HTTP 客户端，同一实例复用连接池以减少握手开销。"""
        if self._client is None:
            headers = {"Accept": "application/vnd.github+json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        """统一请求入口，内置限流重试逻辑。

        GitHub 有两类限速：主限速（X-RateLimit-Reset 头）和次级限速（Retry-After 头）。
        等待时间上限为 120 秒，避免因极端情况导致无限挂起。
        """
        client = await self._get_client()
        response = await client.request(method, path, **kwargs)

        # Handle rate limiting with retry
        if response.status_code in (403, 429):
            text_lower = response.text.lower()
            if "rate limit" in text_lower or response.status_code == 429:
                reset_time = int(response.headers.get("X-RateLimit-Reset", "0"))
                now_utc = int(datetime.now(timezone.utc).timestamp())
                wait = max(reset_time - now_utc, 1)

                # Secondary rate limits use Retry-After header
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    wait = min(int(retry_after), 120)
                else:
                    wait = min(wait, 120)

                await asyncio.sleep(wait)
                response = await client.request(method, path, **kwargs)

                # If still rate limited after retry, raise
                if response.status_code in (403, 429):
                    response.raise_for_status()

        response.raise_for_status()
        return response.json()

    async def list_workflow_runs(
        self,
        owner: str,
        repo: str,
        filters: AnalysisFilters | None = None,
        per_page: int = 30,
    ) -> list[dict]:
        """Fetch recent workflow runs with optional filters.

        GitHub API 只支持单值的 branch/status 过滤；多值情况改为客户端本地过滤。
        """
        params: dict = {"per_page": per_page}

        if filters:
            if filters.branches and len(filters.branches) == 1:
                params["branch"] = filters.branches[0]
            if filters.status and len(filters.status) == 1:
                # GitHub API uses "conclusion" for completed runs
                params["status"] = filters.status[0]
            if filters.time_range:
                params["created"] = (
                    f"{filters.time_range[0].strftime('%Y-%m-%dT%H:%M:%SZ')}..{filters.time_range[1].strftime('%Y-%m-%dT%H:%M:%SZ')}"
                )

        data = await self._request("GET", f"/repos/{owner}/{repo}/actions/runs", params=params)
        runs = data.get("workflow_runs", [])

        # Apply client-side filters that GitHub API doesn't support directly
        if filters:
            if filters.workflows:
                runs = [r for r in runs if r.get("name") in filters.workflows or r.get("path", "").split("/")[-1] in filters.workflows]
            if filters.branches and len(filters.branches) > 1:
                runs = [r for r in runs if r.get("head_branch") in filters.branches]
            if filters.status and len(filters.status) > 1:
                runs = [r for r in runs if r.get("conclusion") in filters.status or r.get("status") in filters.status]

        return runs

    async def get_run_jobs(self, owner: str, repo: str, run_id: int, filter: str = "latest") -> list[dict]:
        """Get jobs for a specific workflow run.

        Args:
            filter: "latest" for most recent attempt only, "all" for all attempts.
        """
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            params={"filter": filter},
        )
        return data.get("jobs", [])

    async def get_run_logs(self, owner: str, repo: str, run_id: int, max_lines: int = 2000) -> str | None:
        """Download and extract failure logs for a run. Returns truncated log text.

        GitHub 返回的是包含多个 job 日志文件的 ZIP；此处合并所有文件并取尾部行，
        因为错误通常出现在运行末尾。BadZipFile 时降级为纯文本处理。
        """
        client = await self._get_client()
        try:
            response = await client.get(
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
                follow_redirects=True,
            )
            if response.status_code == 200:
                # Response is a zip file containing log text files
                try:
                    zf = zipfile.ZipFile(io.BytesIO(response.content))
                    all_lines: list[str] = []
                    for name in zf.namelist():
                        if name.endswith(".txt") or "/" in name:
                            try:
                                text = zf.read(name).decode("utf-8", errors="replace")
                                all_lines.extend(text.split("\n"))
                            except (KeyError, UnicodeDecodeError):
                                pass
                    zf.close()
                    if len(all_lines) > max_lines:
                        all_lines = all_lines[-max_lines:]
                    return "\n".join(all_lines) if all_lines else None
                except zipfile.BadZipFile:
                    # Fallback: treat as plain text
                    text = response.text
                    lines = text.split("\n")
                    if len(lines) > max_lines:
                        lines = lines[-max_lines:]
                    return "\n".join(lines)
        except httpx.HTTPError:
            pass
        return None

    async def get_job_log(
        self,
        owner: str,
        repo: str,
        job_id: int,
        max_lines: int = 2000,
    ) -> str | None:
        """Download the log for a single job. Returns truncated plain text.

        Unlike ``get_run_logs`` (which returns the whole-run ZIP), this hits
        the per-job endpoint and returns just that job's log directly as text.
        """
        client = await self._get_client()
        try:
            response = await client.get(
                f"/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
                follow_redirects=True,
            )
            if response.status_code != 200:
                return None
            text = response.text
            lines = text.split("\n")
            if len(lines) > max_lines:
                lines = lines[-max_lines:]
            return "\n".join(lines) if lines else None
        except httpx.HTTPError:
            return None

    async def get_workflows(self, owner: str, repo: str) -> list[dict]:
        """List all workflows in the repo."""
        data = await self._request("GET", f"/repos/{owner}/{repo}/actions/workflows")
        return data.get("workflows", [])

    async def get_workflow_timing(self, owner: str, repo: str, run_id: int) -> dict | None:
        """Get timing/billing info for a workflow run."""
        try:
            data = await self._request("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}/timing")
            return data
        except httpx.HTTPStatusError:
            return None

    async def get_repo_info(self, owner: str, repo: str) -> dict:
        """Get repository metadata."""
        return await self._request("GET", f"/repos/{owner}/{repo}")

    async def resolve_action_sha(self, owner: str, repo: str, ref: str) -> str | None:
        """Resolve a tag/branch ref to its full commit SHA.

        Tries tag ref first, then branch, returns None if not found.

        先尝试 tag，再尝试 branch，顺序与 GitHub 官方推荐一致。
        注解标签（annotated tag）需要额外一次请求跟随到真正的 commit SHA。
        """
        for ref_path in [f"tags/{ref}", f"heads/{ref}"]:
            try:
                data = await self._request("GET", f"/repos/{owner}/{repo}/git/ref/{ref_path}")
                obj = data.get("object", {})
                # Annotated tags point to a tag object — follow to the commit
                if obj.get("type") == "tag":
                    tag_data = await self._request("GET", f"/repos/{owner}/{repo}/git/tags/{obj['sha']}")
                    return tag_data.get("object", {}).get("sha")
                return obj.get("sha")
            except Exception:
                continue
        return None
