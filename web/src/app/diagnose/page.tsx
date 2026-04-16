'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import FailureDiagnosisCard from '@/components/FailureDiagnosisCard';
import { diagnoseRun, getFailedRuns } from '@/lib/api';
import { interpolate, useLocale } from '@/lib/locale';
import type {
  DiagnoseResponse,
  DiagnoseTier,
  FailedRunSummary,
} from '@/types';

/** Extract {repo, runId, attempt} from a GitHub Actions run URL, or null. */
function parseGitHubRunUrl(raw: string): {
  repo: string | null;
  runId: number | null;
  attempt: number | null;
} {
  const trimmed = raw.trim();
  const runMatch = trimmed.match(
    /github\.com\/([\w.-]+\/[\w.-]+)\/actions\/runs\/(\d+)(?:\/attempts\/(\d+))?/,
  );
  if (runMatch) {
    return {
      repo: runMatch[1],
      runId: parseInt(runMatch[2], 10),
      attempt: runMatch[3] ? parseInt(runMatch[3], 10) : null,
    };
  }
  const slashMatch = trimmed.match(/^([\w.-]+\/[\w.-]+)$/);
  if (slashMatch) return { repo: slashMatch[1], runId: null, attempt: null };
  return { repo: null, runId: null, attempt: null };
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return '—';
  const ts = new Date(iso).getTime();
  const diff = Date.now() - ts;
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return 'today';
  if (days === 1) return '1 day ago';
  if (days < 30) return `${days} days ago`;
  if (days < 60) return '1 month ago';
  return `${Math.floor(days / 30)} months ago`;
}

// ── Step 1: Repo input ─────────────────────────────────────────────────────

function RepoInputStep({
  initialRepo,
  onSubmit,
  loading,
}: {
  initialRepo: string;
  onSubmit: (repo: string, directRunId?: number, directAttempt?: number) => void;
  loading: boolean;
}) {
  const { t } = useLocale();
  const [value, setValue] = useState(initialRepo);

  useEffect(() => setValue(initialRepo), [initialRepo]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = parseGitHubRunUrl(value);
    if (!parsed.repo) return;
    // If user pasted a full URL, skip the picker and diagnose directly.
    if (parsed.runId) {
      onSubmit(parsed.repo, parsed.runId, parsed.attempt ?? 1);
    } else {
      onSubmit(parsed.repo);
    }
  };

  const canSubmit = parseGitHubRunUrl(value).repo !== null;

  return (
    <form onSubmit={handleSubmit} className="card space-y-4">
      <p className="text-xs text-slate-500">{t('diag.form.help')}</p>
      <div className="flex flex-col sm:flex-row gap-3">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t('diag.form.repo_placeholder')}
          className="flex-1 px-4 py-2.5 text-sm rounded-lg bg-surface-elevated text-slate-200 border border-surface-border focus:border-accent-blue focus:outline-none font-mono"
          autoFocus
        />
        <button
          type="submit"
          disabled={!canSubmit || loading}
          className="px-6 py-2.5 text-sm font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
        >
          {loading ? t('diag.form.submitting') : t('diag.form.submit')}
        </button>
      </div>
    </form>
  );
}

// ── Step 2: Failures picker ────────────────────────────────────────────────

/** Group runs by workflow name, keeping each group sorted by most-recent first. */
function groupByWorkflow(
  runs: FailedRunSummary[],
): { workflow: string; runs: FailedRunSummary[] }[] {
  const buckets = new Map<string, FailedRunSummary[]>();
  for (const r of runs) {
    const key = r.workflow;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(r);
  }
  // Sort groups by their most recent failure time (desc)
  return Array.from(buckets.entries())
    .map(([workflow, list]) => {
      const sorted = [...list].sort(
        (a, b) =>
          new Date(b.created_at ?? 0).getTime() -
          new Date(a.created_at ?? 0).getTime(),
      );
      return { workflow, runs: sorted };
    })
    .sort((a, b) => {
      const at = new Date(a.runs[0].created_at ?? 0).getTime();
      const bt = new Date(b.runs[0].created_at ?? 0).getTime();
      return bt - at;
    });
}

function WorkflowGroup({
  workflow,
  runs,
  defaultOpen,
  onDiagnose,
  diagnosingRun,
}: {
  workflow: string;
  runs: FailedRunSummary[];
  defaultOpen: boolean;
  onDiagnose: (run: FailedRunSummary) => void;
  diagnosingRun: number | null;
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(defaultOpen);
  const latest = runs[0];
  const multi = runs.length > 1;

  return (
    <div className="border-t border-surface-border first:border-t-0">
      {/* Group header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-elevated/50 transition-colors text-left"
      >
        <span
          className={`text-slate-500 text-xs transition-transform ${open ? 'rotate-90' : ''}`}
          aria-hidden="true"
        >
          ▶
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-slate-200 font-medium truncate">{workflow}</span>
            <span className="text-xs px-1.5 py-0.5 rounded-full bg-red-500/15 text-red-400 font-medium">
              {interpolate(t('diag.picker.group_count'), { count: runs.length })}
            </span>
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            {interpolate(t('diag.picker.latest'), { time: formatRelativeTime(latest.created_at) })}
            {latest.branch && (
              <>
                {' · '}
                <span className="font-mono">
                  {latest.branch.replace(/^refs\/(pull|heads)\//, '')}
                </span>
              </>
            )}
          </div>
        </div>
        {multi ? null : (
          // Single-run group: show inline [Diagnose] button, skip expand
          <span
            role="button"
            onClick={(e) => {
              e.stopPropagation();
              onDiagnose(latest);
            }}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-accent-blue/15 text-accent-blue hover:bg-accent-blue/25 transition-colors"
          >
            {diagnosingRun === latest.run_id
              ? t('diag.picker.diagnosing')
              : t('diag.picker.diagnose')}
          </span>
        )}
        {multi && (
          <span
            role="button"
            onClick={(e) => {
              e.stopPropagation();
              onDiagnose(latest);
            }}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-accent-blue/15 text-accent-blue hover:bg-accent-blue/25 transition-colors whitespace-nowrap"
          >
            {diagnosingRun === latest.run_id
              ? t('diag.picker.diagnosing')
              : t('diag.picker.diagnose_latest')}
          </span>
        )}
      </button>

      {/* Expanded run list (only if multi + open) */}
      {open && multi && (
        <div className="bg-surface-elevated/30">
          <table className="w-full text-sm">
            <tbody>
              {runs.map((r) => (
                <tr
                  key={`${r.run_id}-${r.run_attempt}`}
                  className="border-t border-surface-border/50"
                >
                  <td className="pl-10 pr-4 py-2">
                    <div className="flex items-center gap-2">
                      {r.html_url ? (
                        <a
                          href={r.html_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-slate-400 hover:text-accent-blue font-mono"
                        >
                          #{r.run_id}
                        </a>
                      ) : (
                        <span className="text-xs text-slate-400 font-mono">
                          #{r.run_id}
                        </span>
                      )}
                      {r.run_attempt > 1 && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-orange-400/15 text-orange-400">
                          {interpolate(t('diag.picker.attempt'), { n: r.run_attempt })}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-slate-400 font-mono text-xs">
                    {r.branch?.replace(/^refs\/(pull|heads)\//, '') ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-slate-500 text-xs hidden md:table-cell">
                    {r.actor ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-slate-500 text-xs hidden md:table-cell">
                    {formatRelativeTime(r.created_at)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => onDiagnose(r)}
                      disabled={diagnosingRun !== null}
                      className="px-3 py-1 text-xs font-medium rounded bg-accent-blue/10 text-accent-blue hover:bg-accent-blue/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {diagnosingRun === r.run_id
                        ? t('diag.picker.diagnosing')
                        : t('diag.picker.diagnose')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FailuresPicker({
  repo,
  runs,
  onDiagnose,
  diagnosingRun,
  onChangeRepo,
}: {
  repo: string;
  runs: FailedRunSummary[];
  onDiagnose: (run: FailedRunSummary) => void;
  diagnosingRun: number | null;
  onChangeRepo: () => void;
}) {
  const { t } = useLocale();
  const [allOpen, setAllOpen] = useState<boolean | null>(null);
  const groups = groupByWorkflow(runs);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">
            {t('diag.picker.title')}
          </h2>
          <p className="text-sm text-slate-400">
            <span className="font-mono text-accent-blue">{repo}</span>
            {' · '}
            {interpolate(t('diag.picker.subtitle'), {
              count: runs.length,
              groups: groups.length,
            })}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {groups.length > 1 && (
            <button
              onClick={() => setAllOpen(!allOpen)}
              className="text-xs text-slate-400 hover:text-accent-blue transition-colors"
            >
              {allOpen ? t('diag.picker.collapse_all') : t('diag.picker.expand_all')}
            </button>
          )}
          <button
            onClick={onChangeRepo}
            className="text-sm text-slate-400 hover:text-accent-blue transition-colors"
          >
            {t('diag.picker.change_repo')}
          </button>
        </div>
      </div>

      {runs.length === 0 ? (
        <div className="card text-center py-12 text-slate-400">
          {t('diag.picker.empty')}
        </div>
      ) : (
        <div className="card overflow-hidden p-0">
          {groups.map((g, i) => (
            <WorkflowGroup
              key={g.workflow}
              workflow={g.workflow}
              runs={g.runs}
              // Default: first group open, rest collapsed; "expand all" override applies
              defaultOpen={allOpen ?? i === 0}
              onDiagnose={onDiagnose}
              diagnosingRun={diagnosingRun}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

type Screen =
  | { type: 'input'; repo: string }
  | { type: 'loading-runs'; repo: string }
  | { type: 'picker'; repo: string; runs: FailedRunSummary[] }
  | {
      type: 'diagnosing';
      repo: string;
      runs: FailedRunSummary[];
      runId: number;
      runAttempt: number;
    };

interface ResultState {
  result: DiagnoseResponse;
  runId: number;
  runAttempt: number;
}

/** Sync diagnosis state to URL without adding a history entry. */
function updateUrl(params: Record<string, string | number | null>) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === '' || value === undefined) {
      url.searchParams.delete(key);
    } else {
      url.searchParams.set(key, String(value));
    }
  }
  window.history.replaceState({}, '', url.toString());
}

function DiagnosePageInner() {
  const { t } = useLocale();
  const searchParams = useSearchParams();

  const [screen, setScreen] = useState<Screen>({ type: 'input', repo: '' });
  // Last successful diagnosis — kept across re-diagnoses so the card doesn't
  // flash to blank while a new run is being analyzed. Also restored from
  // URL query params on initial load (cheap DB-cache hit on the backend).
  const [lastResult, setLastResult] = useState<ResultState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deepLoading, setDeepLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  const mapError = useCallback(
    (msg: string): string => {
      const m = msg.toLowerCase();
      if (m.includes('no failed jobs')) return t('diag.error.no_failures');
      if (m.includes('not found') || m.includes('not accessible'))
        return t('diag.error.not_found');
      if (m.includes('rate limit')) return t('diag.error.rate_limit');
      if (m.includes('diagnos') || m.includes('llm')) return t('diag.error.llm');
      return msg || t('diag.error.generic');
    },
    [t],
  );

  const startDiagnose = useCallback(
    async (
      repo: string,
      runs: FailedRunSummary[],
      runId: number,
      runAttempt: number,
      tier: DiagnoseTier = 'default',
    ) => {
      setScreen({ type: 'diagnosing', repo, runs, runId, runAttempt });
      setError(null);
      if (tier === 'deep') setDeepLoading(true);
      try {
        const resp = await diagnoseRun({
          repo,
          run_id: runId,
          run_attempt: runAttempt,
          tier,
        });
        setLastResult({ result: resp, runId, runAttempt });
        // Persist to URL so page refresh restores the state.
        updateUrl({ repo, run_id: runId, run_attempt: runAttempt, tier });
        // Return to picker if we have a list (so user can pick another),
        // otherwise stay on a minimal screen.
        setScreen(
          runs.length > 0
            ? { type: 'picker', repo, runs }
            : { type: 'input', repo },
        );
      } catch (e) {
        setError(mapError(e instanceof Error ? e.message : 'error'));
        setScreen(
          runs.length > 0
            ? { type: 'picker', repo, runs }
            : { type: 'input', repo },
        );
      } finally {
        setDeepLoading(false);
      }
    },
    [mapError],
  );

  const handleRepoSubmit = useCallback(
    async (repo: string, directRunId?: number, directAttempt?: number) => {
      setError(null);
      // URL with run_id → skip picker
      if (directRunId) {
        await startDiagnose(repo, [], directRunId, directAttempt ?? 1);
        return;
      }
      setScreen({ type: 'loading-runs', repo });
      updateUrl({ repo, run_id: null, run_attempt: null, tier: null });
      try {
        const runs = await getFailedRuns(repo, 20);
        setScreen({ type: 'picker', repo, runs });
      } catch (e) {
        setError(mapError(e instanceof Error ? e.message : 'error'));
        setScreen({ type: 'input', repo });
      }
    },
    [mapError, startDiagnose],
  );

  const handlePick = useCallback(
    (run: FailedRunSummary) => {
      // Allow re-selection from picker, result, or diagnosing screens.
      if (screen.type === 'input' || screen.type === 'loading-runs') return;
      startDiagnose(screen.repo, screen.runs, run.run_id, run.run_attempt);
    },
    [screen, startDiagnose],
  );

  const handleDeep = useCallback(() => {
    if (!lastResult) return;
    // Reuse current screen's repo + runs so picker doesn't disappear
    const repo =
      screen.type === 'picker' || screen.type === 'diagnosing'
        ? screen.repo
        : screen.type === 'loading-runs'
          ? screen.repo
          : screen.repo; // 'input'
    const runs =
      screen.type === 'picker' || screen.type === 'diagnosing' ? screen.runs : [];
    startDiagnose(repo, runs, lastResult.runId, lastResult.runAttempt, 'deep');
  }, [lastResult, screen, startDiagnose]);

  const changeRepo = () => {
    setScreen({ type: 'input', repo: '' });
    setLastResult(null);
    updateUrl({ repo: null, run_id: null, run_attempt: null, tier: null });
  };

  // ── Hydrate from URL on first mount ──────────────────────────────────────
  // URL shape: ?repo=owner/name&run_id=123&run_attempt=1&tier=default
  // Runs exactly once (guarded by `hydrated`). Missing pieces are tolerated.
  useEffect(() => {
    if (hydrated) return;
    const qRepo = searchParams.get('repo');
    const qRunId = searchParams.get('run_id');
    const qAttempt = parseInt(searchParams.get('run_attempt') ?? '1', 10) || 1;
    const qTier = (searchParams.get('tier') ?? 'default') as DiagnoseTier;

    if (!qRepo) {
      setHydrated(true);
      return;
    }

    (async () => {
      // Kick off picker + (optional) diagnosis fetch in parallel.
      const runsPromise = getFailedRuns(qRepo, 20).catch(() => [] as FailedRunSummary[]);

      if (qRunId && /^\d+$/.test(qRunId)) {
        const runId = parseInt(qRunId, 10);
        setScreen({ type: 'diagnosing', repo: qRepo, runs: [], runId, runAttempt: qAttempt });
        try {
          // Backend will exact-cache-hit so this is free on refresh.
          const resp = await diagnoseRun({
            repo: qRepo,
            run_id: runId,
            run_attempt: qAttempt,
            tier: qTier,
          });
          setLastResult({ result: resp, runId, runAttempt: qAttempt });
        } catch (e) {
          setError(mapError(e instanceof Error ? e.message : 'error'));
        }
      }

      const runs = await runsPromise;
      setScreen({ type: 'picker', repo: qRepo, runs });
      setHydrated(true);
    })();
  }, [hydrated, searchParams, mapError]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('diag.title')}</h1>
        <p className="text-slate-400 text-sm mt-1">{t('diag.subtitle')}</p>
      </div>

      {/* Step 1: Input */}
      {(screen.type === 'input' || screen.type === 'loading-runs') && (
        <RepoInputStep
          initialRepo={screen.type === 'input' ? screen.repo : screen.repo}
          onSubmit={handleRepoSubmit}
          loading={screen.type === 'loading-runs'}
        />
      )}

      {/* Inline error */}
      {error && (
        <div className="card border border-red-500/20 bg-red-500/5 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Step 2: Picker (stays visible through diagnosing + after result) */}
      {(screen.type === 'picker' || screen.type === 'diagnosing') && (
        <FailuresPicker
          repo={screen.repo}
          runs={screen.runs}
          onDiagnose={handlePick}
          diagnosingRun={screen.type === 'diagnosing' ? screen.runId : null}
          onChangeRepo={changeRepo}
        />
      )}

      {/* Step 3: Result — kept visible across re-diagnoses */}
      {lastResult && (
        <div className="relative">
          {screen.type === 'diagnosing' && (
            <div className="absolute inset-0 rounded-xl bg-surface-bg/60 backdrop-blur-sm z-10 flex items-center justify-center pointer-events-none">
              <div className="flex items-center gap-2 text-sm text-slate-300 px-4 py-2 rounded-lg bg-surface-elevated shadow">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                {t('diag.form.submitting')}
              </div>
            </div>
          )}
          <FailureDiagnosisCard
            diagnosis={lastResult.result}
            onDeepAnalysis={
              lastResult.result.cost_usd !== null ? handleDeep : undefined
            }
            deepLoading={deepLoading}
          />
        </div>
      )}

      {/* Empty state (first visit, no input yet) */}
      {screen.type === 'input' && !screen.repo && !lastResult && !error && (
        <div className="card text-center py-12">
          <p className="text-slate-300 font-medium">{t('diag.empty.title')}</p>
          <p className="text-slate-500 text-sm mt-1">{t('diag.empty.hint')}</p>
        </div>
      )}
    </div>
  );
}

export default function DiagnosePage() {
  return (
    <Suspense fallback={<div className="card text-slate-400">Loading...</div>}>
      <DiagnosePageInner />
    </Suspense>
  );
}
