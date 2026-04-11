'use client';

import { useEffect, useState } from 'react';
import { getSkills } from '@/lib/api';
import type { Skill } from '@/types';

const DIMENSION_COLOR: Record<string, string> = {
  efficiency: 'border-accent-blue/40 bg-blue-500/5',
  security: 'border-accent-purple/40 bg-purple-500/5',
  cost: 'border-accent-green/40 bg-green-500/5',
  errors: 'border-accent-red/40 bg-red-500/5',
};

const DEFAULT_COLOR = 'border-slate-500/40 bg-slate-500/5';

const SOURCE_BADGE_COLOR: Record<string, string> = {
  builtin: 'bg-blue-500/15 text-blue-300',
  user: 'bg-purple-500/15 text-purple-300',
};

function formatPromptPreview(prompt: string, maxChars = 200): string {
  const cleaned = prompt.trim();
  if (cleaned.length <= maxChars) return cleaned;
  return cleaned.slice(0, maxChars) + '...';
}

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Skill | null>(null);
  const [reloading, setReloading] = useState(false);

  function load() {
    setError(null);
    getSkills()
      .then(setSkills)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(() => {
    load();
  }, []);

  async function handleReload() {
    setReloading(true);
    try {
      const res = await fetch('/api/skills/reload', { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setReloading(false);
    }
  }

  // Close drawer on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setSelected(null);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">Analysis Skills</h1>
          <p className="text-slate-400 text-sm mt-1">
            Built-in and user-defined skills that the agent uses to analyze your CI pipelines.
          </p>
        </div>
        <button
          type="button"
          onClick={handleReload}
          disabled={reloading}
          className="btn-secondary text-sm flex items-center gap-2"
          aria-label="Reload skills from disk"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            className={reloading ? 'animate-spin' : ''}
            aria-hidden="true"
          >
            <path
              d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {reloading ? 'Reloading...' : 'Reload'}
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-sm text-red-400"
        >
          {error}
        </div>
      )}

      {!skills && !error && (
        <div className="card text-center py-12 text-slate-500">Loading skills...</div>
      )}

      {skills && skills.length === 0 && (
        <div className="card text-center py-12 text-slate-500">
          No skills found. Check your <code>skills/</code> directory or <code>~/.ci-agent/skills/</code>.
        </div>
      )}

      {skills && skills.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {skills.map((skill) => {
            const colorClass = DIMENSION_COLOR[skill.dimension] ?? DEFAULT_COLOR;
            const sourceBadge = SOURCE_BADGE_COLOR[skill.source] ?? 'bg-slate-500/15 text-slate-300';
            return (
              <button
                key={skill.name}
                type="button"
                onClick={() => setSelected(skill)}
                className={[
                  'text-left p-4 rounded-xl border transition-all hover:scale-[1.01]',
                  colorClass,
                  !skill.enabled ? 'opacity-50' : '',
                ].join(' ')}
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <span className="text-sm font-semibold text-slate-200 capitalize">
                    {skill.dimension}
                  </span>
                  <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${sourceBadge}`}>
                    {skill.source}
                  </span>
                </div>
                <div className="text-xs text-slate-500 font-mono mb-2">{skill.name}</div>
                <p className="text-xs text-slate-400 line-clamp-3">{skill.description}</p>
                <div className="mt-3 pt-2 border-t border-slate-700/50 flex items-center justify-between text-xs text-slate-500">
                  <span>priority {skill.priority}</span>
                  <span className="font-mono">
                    {skill.requires_data.length} data source{skill.requires_data.length !== 1 ? 's' : ''}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Detail drawer */}
      {selected && (
        <div
          className="fixed inset-0 z-50 flex justify-end"
          role="dialog"
          aria-modal="true"
          aria-labelledby="skill-drawer-title"
        >
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setSelected(null)}
            aria-hidden="true"
          />
          {/* Panel */}
          <div className="relative w-full max-w-2xl h-full bg-surface-card border-l border-surface-border overflow-y-auto">
            <div className="sticky top-0 bg-surface-card border-b border-surface-border px-6 py-4 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 id="skill-drawer-title" className="text-lg font-bold text-white truncate">
                  {selected.name}
                </h2>
                <p className="text-xs text-slate-500 mt-0.5 truncate">{selected.description}</p>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="text-slate-400 hover:text-slate-200 text-2xl leading-none"
                aria-label="Close drawer"
              >
                ×
              </button>
            </div>

            <div className="px-6 py-5 space-y-5">
              {/* Metadata */}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                <div>
                  <dt className="text-xs text-slate-500 uppercase tracking-wide">Dimension</dt>
                  <dd className="text-slate-200 font-mono capitalize">{selected.dimension}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500 uppercase tracking-wide">Source</dt>
                  <dd className="text-slate-200 font-mono">{selected.source}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500 uppercase tracking-wide">Priority</dt>
                  <dd className="text-slate-200 font-mono">{selected.priority}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500 uppercase tracking-wide">Enabled</dt>
                  <dd className="text-slate-200 font-mono">{String(selected.enabled)}</dd>
                </div>
              </dl>

              {/* Tools */}
              <div>
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                  Tools
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {selected.tools.map((t) => (
                    <span
                      key={t}
                      className="text-xs px-2 py-0.5 rounded bg-slate-700/50 text-slate-300 font-mono"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>

              {/* Requires data */}
              <div>
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                  Requires Data
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {selected.requires_data.map((d) => (
                    <span
                      key={d}
                      className="text-xs px-2 py-0.5 rounded bg-slate-700/50 text-slate-300 font-mono"
                    >
                      {d}
                    </span>
                  ))}
                </div>
              </div>

              {/* Prompt body */}
              {selected.prompt && (
                <div>
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                    Prompt ({selected.prompt.length} chars)
                  </h3>
                  <pre className="bg-surface-elevated border border-surface-border rounded-lg px-4 py-3 text-xs font-mono text-slate-300 overflow-x-auto whitespace-pre-wrap max-h-[50vh]">
                    {selected.prompt}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
