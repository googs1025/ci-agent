"""Pre-fetch GitHub data before agent analysis."""

import asyncio
import json
import logging
import math
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Max number of runs to fetch job details for (to avoid rate limiting)
MAX_RUNS_FOR_JOBS = 20

# Max number of workflow files to process (to avoid excessive analysis time)
MAX_WORKFLOW_FILES = 20

from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.github_client import GitHubClient
from ci_optimizer.resolver import ResolvedInput

# Runner billing multipliers (GitHub-hosted)
RUNNER_MULTIPLIERS = {
    "ubuntu": 1,
    "macos": 10,
    "windows": 2,
}


@dataclass
class AnalysisContext:
    """All data needed for agent analysis, pre-fetched and saved locally."""

    local_path: Path
    owner: str | None = None
    repo: str | None = None
    workflow_files: list[Path] = field(default_factory=list)
    runs_json_path: Path | None = None
    jobs_json_path: Path | None = None
    logs_json_path: Path | None = None
    usage_stats_json_path: Path | None = None
    workflows_json_path: Path | None = None
    action_shas_json_path: Path | None = None
    filters: AnalysisFilters | None = None
    repo_info: dict | None = None


def _write_temp_json(data: object, prefix: str) -> Path:
    """Write data to a temp JSON file and return the path."""
    fd, path = tempfile.mkstemp(prefix=f"ci-agent-{prefix}-", suffix=".json")
    with open(fd, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return Path(path)


# Matches `uses: owner/repo@ref` — skips refs that are already full 40-char SHAs
_USES_RE = re.compile(r"uses:\s+([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)@([^\s#]+)")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _extract_action_refs(workflow_files: list[Path]) -> dict[str, tuple[str, str, str]]:
    """Return {action_ref: (owner, repo, ref)} for all non-SHA action pins found in workflows."""
    refs: dict[str, tuple[str, str, str]] = {}
    for wf in workflow_files:
        try:
            content = wf.read_text()
        except OSError:
            continue
        for m in _USES_RE.finditer(content):
            action, ref = m.group(1), m.group(2)
            if _FULL_SHA_RE.match(ref):
                continue  # already pinned — skip
            # Skip docker:// and local paths
            if "/" not in action or action.startswith("."):
                continue
            owner, repo = action.split("/", 1)
            key = f"{action}@{ref}"
            refs[key] = (owner, repo, ref)
    return refs


async def _resolve_action_shas(
    refs: dict[str, tuple[str, str, str]],
    client: GitHubClient,
) -> dict[str, str]:
    """Resolve each action ref to a full commit SHA. Returns {action@ref: sha}."""
    results: dict[str, str] = {}

    async def resolve_one(key: str, owner: str, repo: str, ref: str) -> None:
        sha = await client.resolve_action_sha(owner, repo, ref)
        if sha:
            results[key] = sha
            logger.debug(f"Resolved {key} → {sha[:12]}...")
        else:
            logger.debug(f"Could not resolve SHA for {key}")

    # Batch with concurrency limit to avoid rate limiting
    semaphore = asyncio.Semaphore(5)

    async def limited(key: str, owner: str, repo: str, ref: str) -> None:
        async with semaphore:
            await resolve_one(key, owner, repo, ref)

    await asyncio.gather(
        *[limited(k, o, r, ref) for k, (o, r, ref) in refs.items()],
        return_exceptions=True,
    )
    return results


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _duration_ms(start: str | None, end: str | None) -> int | None:
    s, e = _parse_dt(start), _parse_dt(end)
    if s and e:
        return int((e - s).total_seconds() * 1000)
    return None


def _detect_runner_os(labels: list[str] | None) -> str:
    """Detect OS category from runner labels."""
    if not labels:
        return "unknown"
    joined = " ".join(labels).lower()
    if "macos" in joined or "mac" in joined:
        return "macos"
    if "windows" in joined or "win" in joined:
        return "windows"
    if "ubuntu" in joined or "linux" in joined:
        return "ubuntu"
    return "unknown"


def _compute_usage_stats(runs: list[dict], all_jobs: dict[str, list[dict]]) -> dict:
    """Compute usage statistics from runs and their jobs."""
    stats: dict = {
        "total_runs": len(runs),
        "total_jobs": 0,
        "conclusion_counts": defaultdict(int),
        "runner_distribution": defaultdict(int),
        "billing_estimate": {
            "total_minutes": 0.0,
            "by_os": defaultdict(float),
        },
        "timing": {
            "avg_run_duration_ms": 0,
            "avg_job_duration_ms": 0,
            "avg_queue_wait_ms": 0,
            "max_job_duration_ms": 0,
            "max_queue_wait_ms": 0,
        },
        "per_workflow": {},
        "per_job": {},
        "slowest_steps": [],
    }

    run_durations = []
    job_durations = []
    queue_waits = []
    step_timings = []
    workflow_stats: dict = defaultdict(
        lambda: {
            "count": 0,
            "success": 0,
            "failure": 0,
            "durations_ms": [],
        }
    )
    job_name_stats: dict = defaultdict(
        lambda: {
            "count": 0,
            "success": 0,
            "failure": 0,
            "durations_ms": [],
            "queue_waits_ms": [],
        }
    )

    # Process runs
    for run in runs:
        conclusion = run.get("conclusion") or run.get("status") or "unknown"
        stats["conclusion_counts"][conclusion] += 1

        wf_name = run.get("name", "unknown")
        workflow_stats[wf_name]["count"] += 1
        if conclusion == "success":
            workflow_stats[wf_name]["success"] += 1
        elif conclusion == "failure":
            workflow_stats[wf_name]["failure"] += 1

        dur = _duration_ms(run.get("run_started_at") or run.get("created_at"), run.get("updated_at"))
        if dur and dur > 0:
            run_durations.append(dur)
            workflow_stats[wf_name]["durations_ms"].append(dur)

    # Process jobs
    for run_id_str, jobs in all_jobs.items():
        for job in jobs:
            stats["total_jobs"] += 1

            runner_os = _detect_runner_os(job.get("labels"))
            stats["runner_distribution"][runner_os] += 1

            job_name = job.get("name", "unknown")
            conclusion = job.get("conclusion") or "unknown"
            job_name_stats[job_name]["count"] += 1
            if conclusion == "success":
                job_name_stats[job_name]["success"] += 1
            elif conclusion == "failure":
                job_name_stats[job_name]["failure"] += 1

            # Execution duration
            exec_dur = _duration_ms(job.get("started_at"), job.get("completed_at"))
            if exec_dur and exec_dur > 0:
                job_durations.append(exec_dur)
                job_name_stats[job_name]["durations_ms"].append(exec_dur)

                # Billing estimate: round up to nearest minute × multiplier
                minutes = exec_dur / 60000
                billed = math.ceil(minutes)
                multiplier = RUNNER_MULTIPLIERS.get(runner_os, 1)
                stats["billing_estimate"]["total_minutes"] += billed * multiplier
                stats["billing_estimate"]["by_os"][runner_os] += billed * multiplier

            # Queue wait time
            queue_dur = _duration_ms(job.get("created_at"), job.get("started_at"))
            if queue_dur is not None and queue_dur >= 0:
                queue_waits.append(queue_dur)
                job_name_stats[job_name]["queue_waits_ms"].append(queue_dur)

            # Step-level timings
            for step in job.get("steps", []):
                step_dur = _duration_ms(step.get("started_at"), step.get("completed_at"))
                if step_dur and step_dur > 0:
                    step_timings.append(
                        {
                            "job": job_name,
                            "step": step.get("name", "unknown"),
                            "duration_ms": step_dur,
                            "conclusion": step.get("conclusion"),
                        }
                    )

    # Aggregate timing stats
    if run_durations:
        stats["timing"]["avg_run_duration_ms"] = int(sum(run_durations) / len(run_durations))
    if job_durations:
        stats["timing"]["avg_job_duration_ms"] = int(sum(job_durations) / len(job_durations))
        stats["timing"]["max_job_duration_ms"] = max(job_durations)
    if queue_waits:
        stats["timing"]["avg_queue_wait_ms"] = int(sum(queue_waits) / len(queue_waits))
        stats["timing"]["max_queue_wait_ms"] = max(queue_waits)

    # Per-workflow summary
    for wf_name, ws in workflow_stats.items():
        avg_dur = int(sum(ws["durations_ms"]) / len(ws["durations_ms"])) if ws["durations_ms"] else 0
        stats["per_workflow"][wf_name] = {
            "total_runs": ws["count"],
            "success": ws["success"],
            "failure": ws["failure"],
            "success_rate": round(ws["success"] / ws["count"] * 100, 1) if ws["count"] else 0,
            "avg_duration_ms": avg_dur,
        }

    # Per-job summary
    for jn, js in job_name_stats.items():
        avg_dur = int(sum(js["durations_ms"]) / len(js["durations_ms"])) if js["durations_ms"] else 0
        avg_queue = int(sum(js["queue_waits_ms"]) / len(js["queue_waits_ms"])) if js["queue_waits_ms"] else 0
        stats["per_job"][jn] = {
            "total_runs": js["count"],
            "success": js["success"],
            "failure": js["failure"],
            "success_rate": round(js["success"] / js["count"] * 100, 1) if js["count"] else 0,
            "avg_duration_ms": avg_dur,
            "avg_queue_wait_ms": avg_queue,
        }

    # Slowest steps (top 10)
    step_timings.sort(key=lambda x: x["duration_ms"], reverse=True)
    stats["slowest_steps"] = step_timings[:10]

    # Convert defaultdicts to regular dicts for JSON serialization
    stats["conclusion_counts"] = dict(stats["conclusion_counts"])
    stats["runner_distribution"] = dict(stats["runner_distribution"])
    stats["billing_estimate"]["by_os"] = dict(stats["billing_estimate"]["by_os"])

    return stats


async def prepare_context(
    resolved: ResolvedInput,
    filters: AnalysisFilters | None = None,
    required_data: set[str] | None = None,
) -> AnalysisContext:
    """Pre-fetch all data needed for analysis.

    required_data: set of data types to fetch. None = fetch all (backward compatible).
    Valid values: {"workflows", "runs", "jobs", "logs", "usage_stats"}
    """
    ctx = AnalysisContext(
        local_path=resolved.local_path,
        owner=resolved.owner,
        repo=resolved.repo,
        filters=filters,
    )

    # Collect workflow files (always — local file system, no API cost)
    workflows_dir = resolved.local_path / ".github" / "workflows"
    if workflows_dir.exists():
        ctx.workflow_files = sorted(p for p in workflows_dir.iterdir() if p.suffix in (".yml", ".yaml"))

    if len(ctx.workflow_files) > MAX_WORKFLOW_FILES:
        total = len(ctx.workflow_files)
        logger.warning(
            "Repository has %d workflow files, limiting to %d. "
            "Some workflows will not be analyzed.",
            total,
            MAX_WORKFLOW_FILES,
        )
        ctx.workflow_files = ctx.workflow_files[:MAX_WORKFLOW_FILES]

    if not ctx.workflow_files:
        raise FileNotFoundError(
            f"No GitHub Actions workflow files found in {workflows_dir}. Make sure the repository has .github/workflows/*.yml files."
        )

    # Compute which data types are needed
    # Implicit dependency: usage_stats requires runs + jobs to compute
    need_all = required_data is None
    need_usage = need_all or "usage_stats" in required_data
    need_runs = need_all or "runs" in required_data or "jobs" in required_data or need_usage
    need_jobs = need_all or "jobs" in required_data or need_usage
    need_logs = need_all or "logs" in required_data

    # Fetch GitHub API data if we have owner/repo
    if ctx.owner and ctx.repo:
        client = GitHubClient()
        try:
            runs: list[dict] = []
            all_jobs: dict[str, list[dict]] = {}

            if need_runs:
                runs = await client.list_workflow_runs(ctx.owner, ctx.repo, filters)
                ctx.runs_json_path = _write_temp_json(runs, "runs")

            if need_jobs:
                # Fetch jobs for runs (cap to avoid rate limiting)
                runs_for_jobs = runs[:MAX_RUNS_FOR_JOBS]
                if len(runs) > MAX_RUNS_FOR_JOBS:
                    logger.info(f"Limiting job fetch to {MAX_RUNS_FOR_JOBS}/{len(runs)} runs to avoid API rate limits")
                for i, run in enumerate(runs_for_jobs):
                    run_id = run["id"]
                    try:
                        jobs = await client.get_run_jobs(ctx.owner, ctx.repo, run_id)
                    except Exception as e:
                        logger.warning(f"Failed to fetch jobs for run {run_id}: {e}")
                        continue
                    # Brief pause every 10 requests to stay under secondary rate limits
                    if (i + 1) % 10 == 0:
                        await asyncio.sleep(1)
                    all_jobs[str(run_id)] = [
                        {
                            "id": j.get("id"),
                            "name": j.get("name"),
                            "status": j.get("status"),
                            "conclusion": j.get("conclusion"),
                            "created_at": j.get("created_at"),
                            "started_at": j.get("started_at"),
                            "completed_at": j.get("completed_at"),
                            "runner_id": j.get("runner_id"),
                            "runner_name": j.get("runner_name"),
                            "labels": j.get("labels", []),
                            "steps": [
                                {
                                    "name": s.get("name"),
                                    "status": s.get("status"),
                                    "conclusion": s.get("conclusion"),
                                    "number": s.get("number"),
                                    "started_at": s.get("started_at"),
                                    "completed_at": s.get("completed_at"),
                                }
                                for s in j.get("steps", [])
                            ],
                        }
                        for j in jobs
                    ]
                ctx.jobs_json_path = _write_temp_json(all_jobs, "jobs")

            if need_usage and runs and all_jobs:
                # Compute usage stats
                usage_stats = _compute_usage_stats(runs, all_jobs)
                ctx.usage_stats_json_path = _write_temp_json(usage_stats, "usage")

            if need_logs and runs:
                # Fetch failure logs (limit to 5 most recent failed runs)
                failed_runs = [r for r in runs if r.get("conclusion") == "failure"][:5]
                logs = {}
                for run in failed_runs:
                    run_id = run["id"]
                    run_jobs = all_jobs.get(str(run_id), [])
                    failed_jobs = [j for j in run_jobs if j.get("conclusion") == "failure"]
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
                                "steps": [s for s in j.get("steps", []) if s.get("conclusion") == "failure"],
                            }
                            for j in failed_jobs
                        ],
                        "log_excerpt": log_text,
                    }
                ctx.logs_json_path = _write_temp_json(logs, "logs")

            # Always fetch workflow definitions and repo info when we have owner/repo
            workflows = await client.get_workflows(ctx.owner, ctx.repo)
            ctx.workflows_json_path = _write_temp_json(workflows, "workflows")
            ctx.repo_info = await client.get_repo_info(ctx.owner, ctx.repo)

            # Resolve action SHAs when requested (e.g. by security skill)
            need_action_shas = need_all or "action_shas" in (required_data or set())
            if need_action_shas and ctx.workflow_files:
                action_refs = _extract_action_refs(ctx.workflow_files)
                if action_refs:
                    logger.info(f"Resolving SHAs for {len(action_refs)} action ref(s)...")
                    shas = await _resolve_action_shas(action_refs, client)
                    ctx.action_shas_json_path = _write_temp_json(shas, "action-shas")
                    logger.info(f"Resolved {len(shas)}/{len(action_refs)} action SHAs")

        finally:
            await client.close()

    return ctx
