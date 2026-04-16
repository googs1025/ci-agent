'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import FailureDiagnosisCard from '@/components/FailureDiagnosisCard';
import { diagnoseRun } from '@/lib/api';
import { useLocale } from '@/lib/locale';
import type { DiagnoseResponse, DiagnoseTier } from '@/types';

/**
 * Parse a GitHub Actions run URL to extract owner/repo and run_id.
 * Accepted shapes:
 *   https://github.com/OWNER/REPO/actions/runs/12345
 *   https://github.com/OWNER/REPO/actions/runs/12345/attempts/2
 *   OWNER/REPO   (just owner/repo, no run id)
 */
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

function DiagnosePageInner() {
  const { t } = useLocale();
  const searchParams = useSearchParams();

  // Form state
  const [repo, setRepo] = useState('');
  const [runIdInput, setRunIdInput] = useState('');
  const [runAttempt, setRunAttempt] = useState(1);
  const [tier, setTier] = useState<DiagnoseTier>('default');

  // Submission state
  const [loading, setLoading] = useState(false);
  const [deepLoading, setDeepLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DiagnoseResponse | null>(null);

  // Hydrate form from ?repo= & ?run_id= on first mount
  useEffect(() => {
    const q = searchParams.get('repo');
    const r = searchParams.get('run_id');
    const a = searchParams.get('run_attempt');
    if (q) setRepo(q);
    if (r) setRunIdInput(r);
    if (a) setRunAttempt(parseInt(a, 10) || 1);
  }, [searchParams]);

  const handleRepoPaste = useCallback((value: string) => {
    const parsed = parseGitHubRunUrl(value);
    if (parsed.repo) {
      setRepo(parsed.repo);
      if (parsed.runId !== null) setRunIdInput(String(parsed.runId));
      if (parsed.attempt !== null) setRunAttempt(parsed.attempt);
    } else {
      setRepo(value);
    }
  }, []);

  const submit = useCallback(
    async (chosenTier: DiagnoseTier) => {
      const runId = parseInt(runIdInput, 10);
      if (!repo || !Number.isFinite(runId) || runId <= 0) {
        setError(t('diag.error.generic'));
        return;
      }

      if (chosenTier === 'deep') setDeepLoading(true);
      else setLoading(true);
      setError(null);

      try {
        const resp = await diagnoseRun({
          repo,
          run_id: runId,
          run_attempt: runAttempt,
          tier: chosenTier,
        });
        setResult(resp);
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'error';
        if (msg.toLowerCase().includes('no failed jobs')) {
          setError(t('diag.error.no_failures'));
        } else if (msg.toLowerCase().includes('not found')) {
          setError(t('diag.error.not_found'));
        } else if (msg.toLowerCase().includes('rate limit')) {
          setError(t('diag.error.rate_limit'));
        } else if (msg.toLowerCase().includes('diagnos')) {
          setError(t('diag.error.llm'));
        } else {
          setError(msg);
        }
      } finally {
        setLoading(false);
        setDeepLoading(false);
      }
    },
    [repo, runIdInput, runAttempt, t],
  );

  const onSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      submit(tier);
    },
    [submit, tier],
  );

  const onDeepAnalysis = useCallback(() => {
    submit('deep');
  }, [submit]);

  const canSubmit = repo.trim().includes('/') && runIdInput.trim().length > 0;

  return (
    <div className="space-y-8">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-white">{t('diag.title')}</h1>
        <p className="text-slate-400 text-sm mt-1">{t('diag.subtitle')}</p>
      </div>

      {/* Input form */}
      <form onSubmit={onSubmit} className="card space-y-4">
        <p className="text-xs text-slate-500">{t('diag.form.help')}</p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-xs uppercase tracking-wider text-slate-400">
              {t('diag.form.repo')}
            </span>
            <input
              type="text"
              value={repo}
              onChange={(e) => handleRepoPaste(e.target.value)}
              placeholder={t('diag.form.repo_placeholder')}
              className="mt-1 w-full px-3 py-2 text-sm rounded-lg bg-surface-elevated text-slate-200 border border-surface-border focus:border-accent-blue focus:outline-none"
            />
          </label>

          <label className="block">
            <span className="text-xs uppercase tracking-wider text-slate-400">
              {t('diag.form.run_id')}
            </span>
            <input
              type="number"
              inputMode="numeric"
              value={runIdInput}
              onChange={(e) => setRunIdInput(e.target.value)}
              placeholder={t('diag.form.run_id_placeholder')}
              className="mt-1 w-full px-3 py-2 text-sm rounded-lg bg-surface-elevated text-slate-200 border border-surface-border focus:border-accent-blue focus:outline-none font-mono"
            />
          </label>

          <label className="block">
            <span className="text-xs uppercase tracking-wider text-slate-400">
              {t('diag.form.run_attempt')}
            </span>
            <input
              type="number"
              inputMode="numeric"
              min={1}
              value={runAttempt}
              onChange={(e) => setRunAttempt(parseInt(e.target.value, 10) || 1)}
              className="mt-1 w-full px-3 py-2 text-sm rounded-lg bg-surface-elevated text-slate-200 border border-surface-border focus:border-accent-blue focus:outline-none font-mono"
            />
          </label>

          <label className="block">
            <span className="text-xs uppercase tracking-wider text-slate-400">
              {t('diag.form.tier')}
            </span>
            <select
              value={tier}
              onChange={(e) => setTier(e.target.value as DiagnoseTier)}
              className="mt-1 w-full px-3 py-2 text-sm rounded-lg bg-surface-elevated text-slate-200 border border-surface-border focus:border-accent-blue focus:outline-none"
            >
              <option value="default">{t('diag.form.tier_default')}</option>
              <option value="deep">{t('diag.form.tier_deep')}</option>
            </select>
          </label>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={!canSubmit || loading}
            className="px-5 py-2 text-sm rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? t('diag.form.submitting') : t('diag.form.submit')}
          </button>
        </div>
      </form>

      {/* Error state */}
      {error && (
        <div className="card border border-red-500/20 bg-red-500/5 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Result */}
      {result && !loading && (
        <FailureDiagnosisCard
          diagnosis={result}
          onDeepAnalysis={result.model.includes('haiku') ? onDeepAnalysis : undefined}
          deepLoading={deepLoading}
        />
      )}

      {/* Empty state */}
      {!result && !loading && !error && (
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
