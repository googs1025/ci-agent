'use client';

import { useState } from 'react';
import type { AnalyzeFilters } from '@/types';

interface FilterPanelProps {
  filters: AnalyzeFilters;
  onChange: (filters: AnalyzeFilters) => void;
}

const STATUS_OPTIONS = [
  { value: 'success', label: 'Success' },
  { value: 'failure', label: 'Failure' },
  { value: 'cancelled', label: 'Cancelled' },
];

export default function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const [workflowInput, setWorkflowInput] = useState('');
  const [branchInput, setBranchInput] = useState('');

  function updateFilter<K extends keyof AnalyzeFilters>(
    key: K,
    value: AnalyzeFilters[K],
  ) {
    onChange({ ...filters, [key]: value });
  }

  function handleStatusToggle(value: string) {
    const current = filters.status ?? [];
    const next = current.includes(value)
      ? current.filter((s) => s !== value)
      : [...current, value];
    updateFilter('status', next.length > 0 ? next : undefined);
  }

  function addWorkflow() {
    const trimmed = workflowInput.trim();
    if (!trimmed) return;
    const current = filters.workflows ?? [];
    if (!current.includes(trimmed)) {
      updateFilter('workflows', [...current, trimmed]);
    }
    setWorkflowInput('');
  }

  function removeWorkflow(w: string) {
    const next = (filters.workflows ?? []).filter((v) => v !== w);
    updateFilter('workflows', next.length > 0 ? next : undefined);
  }

  function addBranch() {
    const trimmed = branchInput.trim();
    if (!trimmed) return;
    const current = filters.branches ?? [];
    if (!current.includes(trimmed)) {
      updateFilter('branches', [...current, trimmed]);
    }
    setBranchInput('');
  }

  function removeBranch(b: string) {
    const next = (filters.branches ?? []).filter((v) => v !== b);
    updateFilter('branches', next.length > 0 ? next : undefined);
  }

  return (
    <div className="card space-y-6">
      <h2 className="font-semibold text-slate-200 text-base">Filters (optional)</h2>

      {/* Date range */}
      <fieldset>
        <legend className="label">Date range</legend>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-1.5">
          <div>
            <label htmlFor="filter-since" className="text-xs text-slate-500 mb-1 block">
              From
            </label>
            <input
              id="filter-since"
              type="date"
              className="input"
              value={filters.since ?? ''}
              onChange={(e) =>
                updateFilter('since', e.target.value || undefined)
              }
            />
          </div>
          <div>
            <label htmlFor="filter-until" className="text-xs text-slate-500 mb-1 block">
              To
            </label>
            <input
              id="filter-until"
              type="date"
              className="input"
              value={filters.until ?? ''}
              onChange={(e) =>
                updateFilter('until', e.target.value || undefined)
              }
            />
          </div>
        </div>
      </fieldset>

      {/* Run status */}
      <fieldset>
        <legend className="label">Run status</legend>
        <div className="flex flex-wrap gap-3 mt-1.5">
          {STATUS_OPTIONS.map(({ value, label }) => {
            const checked = (filters.status ?? []).includes(value);
            return (
              <label
                key={value}
                className={[
                  'flex items-center gap-2 px-3 py-1.5 rounded-lg border cursor-pointer select-none text-sm transition-colors',
                  checked
                    ? 'border-accent-blue bg-accent-blue/10 text-accent-blue'
                    : 'border-surface-border text-slate-400 hover:border-slate-500',
                ].join(' ')}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={checked}
                  onChange={() => handleStatusToggle(value)}
                  aria-label={`Filter by ${label}`}
                />
                <span
                  className={[
                    'w-4 h-4 flex items-center justify-center rounded border shrink-0 transition-colors',
                    checked ? 'bg-accent-blue border-accent-blue' : 'border-slate-500',
                  ].join(' ')}
                  aria-hidden="true"
                >
                  {checked && (
                    <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                      <path
                        d="M1 4l3 3 5-6"
                        stroke="white"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  )}
                </span>
                {label}
              </label>
            );
          })}
        </div>
      </fieldset>

      {/* Workflow names */}
      <div>
        <label htmlFor="filter-workflow" className="label">
          Workflow names
        </label>
        <div className="flex gap-2">
          <input
            id="filter-workflow"
            type="text"
            className="input"
            placeholder="e.g. CI, deploy.yml"
            value={workflowInput}
            onChange={(e) => setWorkflowInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addWorkflow();
              }
            }}
          />
          <button
            type="button"
            onClick={addWorkflow}
            className="btn-secondary shrink-0"
          >
            Add
          </button>
        </div>
        {(filters.workflows ?? []).length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {(filters.workflows ?? []).map((w) => (
              <span
                key={w}
                className="flex items-center gap-1.5 bg-surface-elevated border border-surface-border text-slate-300 text-xs px-2.5 py-1 rounded-full"
              >
                {w}
                <button
                  type="button"
                  onClick={() => removeWorkflow(w)}
                  className="text-slate-500 hover:text-slate-300 transition-colors"
                  aria-label={`Remove workflow ${w}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Branch names */}
      <div>
        <label htmlFor="filter-branch" className="label">
          Branches
        </label>
        <div className="flex gap-2">
          <input
            id="filter-branch"
            type="text"
            className="input"
            placeholder="e.g. main, develop"
            value={branchInput}
            onChange={(e) => setBranchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addBranch();
              }
            }}
          />
          <button
            type="button"
            onClick={addBranch}
            className="btn-secondary shrink-0"
          >
            Add
          </button>
        </div>
        {(filters.branches ?? []).length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {(filters.branches ?? []).map((b) => (
              <span
                key={b}
                className="flex items-center gap-1.5 bg-surface-elevated border border-surface-border text-slate-300 text-xs px-2.5 py-1 rounded-full"
              >
                {b}
                <button
                  type="button"
                  onClick={() => removeBranch(b)}
                  className="text-slate-500 hover:text-slate-300 transition-colors"
                  aria-label={`Remove branch ${b}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
