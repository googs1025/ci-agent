'use client';

import { useEffect, useState } from 'react';
import { getSkills } from '@/lib/api';
import type { Skill } from '@/types';

interface SkillsSelectorProps {
  selected: string[];           // selected dimension names
  onChange: (selected: string[]) => void;
}

const DIMENSION_COLOR: Record<string, string> = {
  efficiency: 'border-accent-blue/40 bg-blue-500/5',
  security: 'border-accent-purple/40 bg-purple-500/5',
  cost: 'border-accent-green/40 bg-green-500/5',
  errors: 'border-accent-red/40 bg-red-500/5',
};

const DEFAULT_COLOR = 'border-slate-500/40 bg-slate-500/5';

export default function SkillsSelector({ selected, onChange }: SkillsSelectorProps) {
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSkills()
      .then((data) => {
        setSkills(data);
        // Default: all enabled skills selected
        if (selected.length === 0) {
          onChange(data.filter((s) => s.enabled).map((s) => s.dimension));
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggle(dimension: string) {
    if (selected.includes(dimension)) {
      onChange(selected.filter((d) => d !== dimension));
    } else {
      onChange([...selected, dimension]);
    }
  }

  function selectAll() {
    if (!skills) return;
    onChange(skills.filter((s) => s.enabled).map((s) => s.dimension));
  }

  function clearAll() {
    onChange([]);
  }

  if (error) {
    return (
      <div className="card">
        <h2 className="text-base font-semibold text-slate-200 mb-2">Analysis Skills</h2>
        <p className="text-sm text-red-400">Failed to load skills: {error}</p>
      </div>
    );
  }

  if (!skills) {
    return (
      <div className="card">
        <h2 className="text-base font-semibold text-slate-200 mb-2">Analysis Skills</h2>
        <p className="text-sm text-slate-500">Loading skills...</p>
      </div>
    );
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-200">Analysis Skills</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Choose which dimensions to analyze. {skills.length} skill{skills.length !== 1 ? 's' : ''} available.
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={selectAll}
            className="text-slate-400 hover:text-slate-200 transition-colors"
          >
            Select all
          </button>
          <span className="text-slate-600">·</span>
          <button
            type="button"
            onClick={clearAll}
            className="text-slate-400 hover:text-slate-200 transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {skills.map((skill) => {
          const isSelected = selected.includes(skill.dimension);
          const colorClass = DIMENSION_COLOR[skill.dimension] ?? DEFAULT_COLOR;

          return (
            <label
              key={skill.name}
              className={[
                'flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all',
                isSelected
                  ? `${colorClass} border-opacity-100`
                  : 'border-surface-border bg-transparent hover:border-slate-600',
                !skill.enabled ? 'opacity-50 cursor-not-allowed' : '',
              ].join(' ')}
            >
              <input
                type="checkbox"
                checked={isSelected}
                disabled={!skill.enabled}
                onChange={() => toggle(skill.dimension)}
                className="mt-1 accent-accent-blue"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold text-slate-200 capitalize">
                    {skill.dimension}
                  </span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400 font-mono">
                    {skill.source}
                  </span>
                  {!skill.enabled && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-500">
                      disabled
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400 mt-1 line-clamp-2">
                  {skill.description}
                </p>
                <p className="text-xs text-slate-600 mt-1 font-mono">
                  needs: {skill.requires_data.join(', ')}
                </p>
              </div>
            </label>
          );
        })}
      </div>

      {selected.length === 0 && (
        <p className="text-xs text-amber-400">
          ⚠ No skills selected. Analysis will fail.
        </p>
      )}
    </div>
  );
}
