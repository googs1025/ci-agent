'use client';

import { useEffect, useState } from 'react';
import { importSkill, type SkillSourceType } from '@/lib/api';

interface InstallSkillModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: (name: string) => void;
}

const VALID_REQUIRES_DATA = [
  'workflows',
  'runs',
  'jobs',
  'logs',
  'usage_stats',
  'action_shas',
] as const;

const SOURCE_OPTIONS: {
  value: SkillSourceType;
  label: string;
  placeholder: string;
  hint: string;
}[] = [
  {
    value: 'github',
    label: 'GitHub repository',
    placeholder: 'gh:owner/repo  or  https://github.com/owner/repo',
    hint: 'Clones the repo (depth=1) and imports its SKILL.md.',
  },
  {
    value: 'claude-code',
    label: 'Claude Code skill',
    placeholder: 'skill-name (from ~/.claude/skills/)',
    hint: 'Reads from ~/.claude/skills/<name>/SKILL.md and maps fields.',
  },
  {
    value: 'opencode',
    label: 'OpenCode skill',
    placeholder: 'skill-name (from ~/.config/opencode/skills/)',
    hint: 'Reads from ~/.config/opencode/skills/<name>/SKILL.md.',
  },
  {
    value: 'path',
    label: 'Local directory',
    placeholder: '/absolute/path/to/skill-dir',
    hint: 'Imports a directory containing a SKILL.md file.',
  },
];

export default function InstallSkillModal({
  open,
  onClose,
  onSuccess,
}: InstallSkillModalProps) {
  const [sourceType, setSourceType] = useState<SkillSourceType>('github');
  const [source, setSource] = useState('');
  const [dimension, setDimension] = useState('');
  const [requiresData, setRequiresData] = useState<string[]>(['workflows']);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form when modal opens/closes
  useEffect(() => {
    if (!open) {
      setSource('');
      setDimension('');
      setRequiresData(['workflows']);
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !submitting) onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, submitting, onClose]);

  if (!open) return null;

  const active = SOURCE_OPTIONS.find((o) => o.value === sourceType)!;

  function toggleRequires(key: string) {
    setRequiresData((cur) =>
      cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key],
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await importSkill({
        source_type: sourceType,
        source: source.trim(),
        dimension: dimension.trim(),
        requires_data: requiresData.length > 0 ? requiresData : undefined,
      });
      onSuccess(result.name);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="install-modal-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={() => !submitting && onClose()}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative w-full max-w-lg bg-surface-card border border-surface-border rounded-xl shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-surface-card border-b border-surface-border px-6 py-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="install-modal-title" className="text-lg font-bold text-white">
              Install Skill
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Import a SKILL.md from an external source
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="text-slate-400 hover:text-slate-200 text-2xl leading-none disabled:opacity-50"
            aria-label="Close modal"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5">
          {/* Source type */}
          <div>
            <label className="label">Source Type</label>
            <div className="grid grid-cols-2 gap-2 mt-1">
              {SOURCE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setSourceType(opt.value)}
                  disabled={submitting}
                  className={[
                    'px-3 py-2 rounded-lg text-sm font-medium border transition-colors text-left disabled:opacity-50',
                    sourceType === opt.value
                      ? 'border-accent-blue bg-blue-500/10 text-accent-blue'
                      : 'border-surface-border text-slate-400 hover:text-slate-200 hover:bg-surface-elevated',
                  ].join(' ')}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Source input */}
          <div>
            <label htmlFor="source-input" className="label">
              {active.label === 'GitHub repository' ? 'Repository URL' :
               active.label === 'Local directory' ? 'Absolute Path' : 'Skill Name'}
            </label>
            <input
              id="source-input"
              type="text"
              required
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder={active.placeholder}
              className="input"
              autoComplete="off"
              spellCheck={false}
              disabled={submitting}
            />
            <p className="text-xs text-slate-500 mt-1.5">{active.hint}</p>
          </div>

          {/* Dimension */}
          <div>
            <label htmlFor="dimension-input" className="label">
              Dimension <span className="text-red-400">*</span>
            </label>
            <input
              id="dimension-input"
              type="text"
              required
              value={dimension}
              onChange={(e) => setDimension(e.target.value)}
              placeholder="e.g. efficiency, security, cost, errors, or custom"
              className="input"
              autoComplete="off"
              disabled={submitting}
            />
            <p className="text-xs text-slate-500 mt-1.5">
              Foreign skill formats don&apos;t have a dimension field — you need to assign one.
            </p>
          </div>

          {/* Requires data */}
          <div>
            <label className="label">Data Requirements</label>
            <div className="grid grid-cols-2 gap-1.5 mt-1">
              {VALID_REQUIRES_DATA.map((key) => (
                <label
                  key={key}
                  className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={requiresData.includes(key)}
                    onChange={() => toggleRequires(key)}
                    disabled={submitting}
                    className="accent-accent-blue"
                  />
                  <span className="font-mono text-xs">{key}</span>
                </label>
              ))}
            </div>
            <p className="text-xs text-slate-500 mt-1.5">
              What data the skill needs from prefetch.
            </p>
          </div>

          {/* Warning */}
          <div className="flex items-start gap-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-2 text-xs text-yellow-200">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0 mt-0.5">
              <path d="M12 2L2 20h20L12 2z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
              <path d="M12 9v5M12 17v1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <p>
              Imported skill prompts are sent to your configured LLM. Only import
              from sources you trust.
            </p>
          </div>

          {error && (
            <div
              role="alert"
              className="bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-sm text-red-300"
            >
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="btn-secondary text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !source.trim() || !dimension.trim()}
              className="btn-primary text-sm"
            >
              {submitting ? 'Importing…' : 'Install'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}