'use client';

import { useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import FilterPanel from '@/components/FilterPanel';
import { analyzeRepo, getReport } from '@/lib/api';
import type { AnalyzeFilters } from '@/types';

type Phase =
  | { type: 'idle' }
  | { type: 'submitting' }
  | { type: 'polling'; reportId: string; dots: number }
  | { type: 'error'; message: string };

function normalizeRepo(raw: string): string {
  // Accept:
  //   https://github.com/owner/repo(.git)
  //   github.com/owner/repo
  //   owner/repo
  //   /absolute/local/path  (returned as-is)
  const cleaned = raw.trim().replace(/\.git$/, '');
  const ghMatch = cleaned.match(/(?:github\.com\/|https?:\/\/github\.com\/)([^/]+\/[^/]+)/);
  if (ghMatch) return ghMatch[1];
  return cleaned;
}

export default function AnalyzePage() {
  const router = useRouter();
  const [repoInput, setRepoInput] = useState('');
  const [filters, setFilters] = useState<AnalyzeFilters>({});
  const [phase, setPhase] = useState<Phase>({ type: 'idle' });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPolling() {
    if (pollRef.current != null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const repo = normalizeRepo(repoInput);
    if (!repo) return;

    setPhase({ type: 'submitting' });

    try {
      const { report_id } = await analyzeRepo({ repo, filters });
      setPhase({ type: 'polling', reportId: report_id, dots: 0 });

      // Animate dots independently
      let dots = 0;
      const dotsInterval = setInterval(() => {
        dots = (dots + 1) % 4;
        setPhase((prev) =>
          prev.type === 'polling' ? { ...prev, dots } : prev,
        );
      }, 500);

      // Poll every 3 seconds
      pollRef.current = setInterval(async () => {
        try {
          const report = await getReport(report_id);
          if (report.status === 'completed' || report.status === 'failed') {
            stopPolling();
            clearInterval(dotsInterval);
            router.push(`/reports/${report_id}`);
          }
        } catch {
          // transient fetch errors — keep polling
        }
      }, 3000);

      // Safety timeout: stop after 10 minutes
      setTimeout(() => {
        stopPolling();
        clearInterval(dotsInterval);
        setPhase({
          type: 'error',
          message: 'Analysis is taking too long. Check the Reports page for updates.',
        });
      }, 10 * 60 * 1000);
    } catch (err) {
      setPhase({
        type: 'error',
        message: err instanceof Error ? err.message : 'An unexpected error occurred.',
      });
    }
  }

  function handleReset() {
    stopPolling();
    setPhase({ type: 'idle' });
  }

  const isLoading =
    phase.type === 'submitting' || phase.type === 'polling';

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-white">Analyze Repository</h1>
        <p className="text-slate-400 text-sm mt-1">
          Enter a GitHub repository URL or local path to start a CI pipeline analysis.
        </p>
      </div>

      {/* Error banner */}
      {phase.type === 'error' && (
        <div
          role="alert"
          className="flex items-start gap-3 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-4 text-sm text-red-400"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0 mt-0.5">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
            <path d="M12 8v5M12 15v1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <div className="flex-1">
            <p className="font-medium text-red-300">Analysis failed</p>
            <p className="mt-0.5">{phase.message}</p>
          </div>
          <button
            type="button"
            onClick={handleReset}
            className="text-red-400 hover:text-red-300 transition-colors"
            aria-label="Dismiss error"
          >
            ×
          </button>
        </div>
      )}

      {/* Loading / polling state */}
      {isLoading && (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-col items-center justify-center gap-4 py-16 card"
        >
          {/* Spinner */}
          <svg
            className="animate-spin text-accent-blue"
            width="48"
            height="48"
            viewBox="0 0 48 48"
            fill="none"
            aria-hidden="true"
          >
            <circle
              cx="24"
              cy="24"
              r="20"
              stroke="currentColor"
              strokeWidth="4"
              opacity="0.2"
            />
            <path
              d="M44 24a20 20 0 0 0-20-20"
              stroke="currentColor"
              strokeWidth="4"
              strokeLinecap="round"
            />
          </svg>

          <div className="text-center space-y-1">
            {phase.type === 'submitting' && (
              <p className="text-slate-200 font-medium">Starting analysis...</p>
            )}
            {phase.type === 'polling' && (
              <>
                <p className="text-slate-200 font-medium">
                  Analysis in progress{'.'.repeat(phase.dots)}
                </p>
                <p className="text-slate-500 text-sm">
                  Polling for results every 3 seconds
                </p>
              </>
            )}
          </div>

          <button
            type="button"
            onClick={handleReset}
            className="btn-secondary text-sm mt-2"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Form — hidden while loading */}
      {!isLoading && (
        <form onSubmit={handleSubmit} className="space-y-6" noValidate>
          {/* Repository input */}
          <div className="card space-y-4">
            <div>
              <label htmlFor="repo-input" className="label text-base font-semibold text-slate-200">
                Repository
              </label>
              <div className="relative mt-2">
                <span
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
                  aria-hidden="true"
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <input
                  id="repo-input"
                  type="text"
                  required
                  className="input pl-10"
                  placeholder="https://github.com/owner/repo  or  owner/repo"
                  value={repoInput}
                  onChange={(e) => setRepoInput(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
              <p className="text-xs text-slate-500 mt-1.5">
                Accepts GitHub URLs, <code className="font-mono">owner/repo</code> shorthand, or a local filesystem path.
              </p>
            </div>
          </div>

          {/* Filters */}
          <FilterPanel filters={filters} onChange={setFilters} />

          {/* Submit */}
          <div className="flex justify-end">
            <button
              type="submit"
              className="btn-primary px-8"
              disabled={!repoInput.trim()}
            >
              Start Analysis
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
