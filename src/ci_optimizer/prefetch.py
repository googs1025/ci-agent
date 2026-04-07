"""Pre-fetch GitHub data before agent analysis."""

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.github_client import GitHubClient
from ci_optimizer.resolver import ResolvedInput


@dataclass
class AnalysisContext:
    """All data needed for agent analysis, pre-fetched and saved locally."""

    local_path: Path
    owner: str | None = None
    repo: str | None = None
    workflow_files: list[Path] = field(default_factory=list)
    runs_json_path: Path | None = None
    logs_json_path: Path | None = None
    workflows_json_path: Path | None = None
    filters: AnalysisFilters | None = None
    repo_info: dict | None = None


def _write_temp_json(data: object, prefix: str) -> Path:
    """Write data to a temp JSON file and return the path."""
    fd, path = tempfile.mkstemp(prefix=f"ci-agent-{prefix}-", suffix=".json")
    with open(fd, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return Path(path)


async def prepare_context(
    resolved: ResolvedInput,
    filters: AnalysisFilters | None = None,
) -> AnalysisContext:
    """Pre-fetch all data needed for analysis."""
    ctx = AnalysisContext(
        local_path=resolved.local_path,
        owner=resolved.owner,
        repo=resolved.repo,
        filters=filters,
    )

    # Collect workflow files
    workflows_dir = resolved.local_path / ".github" / "workflows"
    if workflows_dir.exists():
        ctx.workflow_files = sorted(
            p for p in workflows_dir.iterdir()
            if p.suffix in (".yml", ".yaml")
        )

    if not ctx.workflow_files:
        raise FileNotFoundError(
            f"No GitHub Actions workflow files found in {workflows_dir}. "
            "Make sure the repository has .github/workflows/*.yml files."
        )

    # Fetch GitHub API data if we have owner/repo
    if ctx.owner and ctx.repo:
        client = GitHubClient()
        try:
            # Fetch run history
            runs = await client.list_workflow_runs(ctx.owner, ctx.repo, filters)
            ctx.runs_json_path = _write_temp_json(runs, "runs")

            # Fetch failure logs for failed runs (limit to 5 most recent)
            failed_runs = [r for r in runs if r.get("conclusion") == "failure"][:5]
            logs = {}
            for run in failed_runs:
                run_id = run["id"]
                jobs = await client.get_run_jobs(ctx.owner, ctx.repo, run_id)
                failed_jobs = [j for j in jobs if j.get("conclusion") == "failure"]
                log_text = await client.get_run_logs(ctx.owner, ctx.repo, run_id)
                logs[str(run_id)] = {
                    "run": {
                        "id": run_id,
                        "name": run.get("name"),
                        "created_at": run.get("created_at"),
                        "head_branch": run.get("head_branch"),
                    },
                    "failed_jobs": [
                        {
                            "name": j.get("name"),
                            "conclusion": j.get("conclusion"),
                            "started_at": j.get("started_at"),
                            "completed_at": j.get("completed_at"),
                            "steps": [
                                {
                                    "name": s.get("name"),
                                    "conclusion": s.get("conclusion"),
                                    "number": s.get("number"),
                                }
                                for s in j.get("steps", [])
                                if s.get("conclusion") == "failure"
                            ],
                        }
                        for j in failed_jobs
                    ],
                    "log_excerpt": log_text,
                }
            ctx.logs_json_path = _write_temp_json(logs, "logs")

            # Fetch workflow definitions
            workflows = await client.get_workflows(ctx.owner, ctx.repo)
            ctx.workflows_json_path = _write_temp_json(workflows, "workflows")

            # Fetch repo info
            ctx.repo_info = await client.get_repo_info(ctx.owner, ctx.repo)

        finally:
            await client.close()

    return ctx
