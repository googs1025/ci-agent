'use client';

import { Fragment, useState, useCallback } from 'react';
import type { Finding, Severity } from '@/types';
import SeverityBadge from './SeverityBadge';

type SortField = 'severity' | 'title' | 'file_path';
type SortDir = 'asc' | 'desc';
type DiffLine = { type: 'context' | 'add' | 'remove'; text: string };

const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  major: 1,
  minor: 2,
  info: 3,
};

// ── Simple LCS diff ───────────────────────────────────────
function computeDiff(oldText: string, newText: string): DiffLine[] {
  const a = oldText.split('\n');
  const b = newText.split('\n');
  const m = a.length, n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);

  const result: DiffLine[] = [];
  let i = m, j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      result.unshift({ type: 'context', text: a[i - 1] });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.unshift({ type: 'add', text: b[j - 1] });
      j--;
    } else {
      result.unshift({ type: 'remove', text: a[i - 1] });
      i--;
    }
  }
  return result;
}

// ── Copy button ───────────────────────────────────────────
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  }, [text]);

  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); handleCopy(); }}
      className="text-xs px-2 py-0.5 rounded font-medium transition-all bg-surface-elevated hover:bg-surface-border text-slate-400 hover:text-slate-200 border border-surface-border"
      aria-label="Copy to clipboard"
    >
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  );
}

// ── Unified diff view ─────────────────────────────────────
function DiffView({ current, suggested }: { current?: string | null; suggested?: string | null }) {
  if (!current && !suggested) return null;

  // Only one side exists — show as plain block
  if (!current || !suggested) {
    const text = (current ?? suggested)!;
    const isOld = Boolean(current);
    return (
      <div>
        <div className="flex items-center justify-between mb-1">
          <p className={`text-xs font-semibold uppercase tracking-wide ${isOld ? 'text-red-400' : 'text-green-400'}`}>
            {isOld ? 'Current Code' : 'Suggested Code'}
          </p>
          <CopyButton text={text} />
        </div>
        <pre className={`border rounded-lg px-4 py-3 text-xs font-mono text-slate-300 overflow-x-auto whitespace-pre ${isOld ? 'bg-red-500/5 border-red-500/20' : 'bg-green-500/5 border-green-500/20'}`}>
          {text}
        </pre>
      </div>
    );
  }

  const diff = computeDiff(current, suggested);
  const removedCount = diff.filter((l) => l.type === 'remove').length;
  const addedCount = diff.filter((l) => l.type === 'add').length;

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
          Code Changes
          {(removedCount > 0 || addedCount > 0) && (
            <span className="ml-2 font-normal normal-case text-slate-500">
              <span className="text-red-400">−{removedCount}</span>
              {' '}
              <span className="text-green-400">+{addedCount}</span>
            </span>
          )}
        </p>
        <CopyButton text={suggested} />
      </div>
      <div className="border border-surface-border rounded-lg overflow-hidden">
        <pre className="text-xs font-mono overflow-x-auto">
          {diff.map((line, idx) => (
            <div
              key={idx}
              className={
                line.type === 'remove'
                  ? 'bg-red-500/10 text-red-300'
                  : line.type === 'add'
                  ? 'bg-green-500/10 text-green-300'
                  : 'text-slate-400'
              }
            >
              <span
                className={`inline-block w-6 shrink-0 text-center select-none ${
                  line.type === 'remove' ? 'text-red-500' : line.type === 'add' ? 'text-green-500' : 'text-slate-600'
                }`}
              >
                {line.type === 'remove' ? '-' : line.type === 'add' ? '+' : ' '}
              </span>
              <span className="whitespace-pre">{line.text}</span>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

// ── Sort helpers ──────────────────────────────────────────
function sortFindings(findings: Finding[], field: SortField, dir: SortDir): Finding[] {
  return [...findings].sort((a, b) => {
    let cmp = 0;
    if (field === 'severity') cmp = (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9);
    else if (field === 'title') cmp = a.title.localeCompare(b.title);
    else if (field === 'file_path') cmp = (a.file_path ?? '').localeCompare(b.file_path ?? '');
    return dir === 'asc' ? cmp : -cmp;
  });
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"
      className={`inline-block ml-1 transition-opacity ${active ? 'opacity-100' : 'opacity-30'}`}>
      <path d={dir === 'asc' || !active ? 'M7 3L10 7H4L7 3Z' : 'M7 11L4 7H10L7 11Z'} fill="currentColor" />
    </svg>
  );
}

// ── Main component ────────────────────────────────────────
export default function FindingTable({ findings }: { findings: Finding[] }) {
  const [sortField, setSortField] = useState<SortField>('severity');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  function handleSort(field: SortField) {
    if (field === sortField) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortField(field); setSortDir('asc'); }
  }

  const sorted = sortFindings(findings, sortField, sortDir);

  if (findings.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">No findings in this dimension.</div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-surface-border">
      <table className="w-full text-sm" aria-label="Findings table">
        <thead>
          <tr className="border-b border-surface-border bg-surface-elevated">
            <th scope="col"
              className="px-4 py-3 text-left font-semibold text-slate-400 cursor-pointer select-none whitespace-nowrap w-28"
              onClick={() => handleSort('severity')}
              aria-sort={sortField === 'severity' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
              Severity <SortIcon active={sortField === 'severity'} dir={sortDir} />
            </th>
            <th scope="col"
              className="px-4 py-3 text-left font-semibold text-slate-400 cursor-pointer select-none"
              onClick={() => handleSort('title')}
              aria-sort={sortField === 'title' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
              Title <SortIcon active={sortField === 'title'} dir={sortDir} />
            </th>
            <th scope="col"
              className="px-4 py-3 text-left font-semibold text-slate-400 cursor-pointer select-none hidden md:table-cell"
              onClick={() => handleSort('file_path')}
              aria-sort={sortField === 'file_path' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
              File <SortIcon active={sortField === 'file_path'} dir={sortDir} />
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((finding) => {
            const isExpanded = expandedId === finding.id;
            return (
              <Fragment key={finding.id}>
                <tr
                  className="border-b border-surface-border last:border-0 table-row-hover"
                  onClick={() => setExpandedId(isExpanded ? null : finding.id)}
                  aria-expanded={isExpanded}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setExpandedId(isExpanded ? null : finding.id);
                    }
                  }}
                >
                  <td className="px-4 py-3 whitespace-nowrap">
                    <SeverityBadge severity={finding.severity} />
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-200">
                    <span className="flex items-center gap-2">
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"
                        className={`shrink-0 text-slate-500 transition-transform duration-150 ${isExpanded ? 'rotate-90' : ''}`}>
                        <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      {finding.title}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400 hidden md:table-cell">
                    {finding.file_path ? (
                      <>
                        {finding.file_path}
                        {finding.line != null && <span className="text-slate-600">:{finding.line}</span>}
                      </>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                </tr>

                {isExpanded && (
                  <tr className="border-b border-surface-border bg-surface-elevated">
                    <td colSpan={3} className="px-6 py-5">
                      <div className="space-y-4 text-sm max-w-4xl">
                        {/* Meta row */}
                        <div className="flex items-center gap-4 flex-wrap text-xs">
                          {finding.skill_name && (
                            <span className="flex items-center gap-1.5">
                              <span className="text-slate-500 uppercase tracking-wide font-semibold">Skill</span>
                              <code className="text-accent-purple font-mono bg-accent-purple/10 px-1.5 py-0.5 rounded">{finding.skill_name}</code>
                            </span>
                          )}
                          {finding.file_path && (
                            <span className="flex items-center gap-1.5">
                              <span className="text-slate-500 uppercase tracking-wide font-semibold">File</span>
                              <code className="text-slate-300 font-mono">
                                {finding.file_path}{finding.line != null && `:${finding.line}`}
                              </code>
                            </span>
                          )}
                        </div>

                        {finding.description && (
                          <div>
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Description</p>
                            <p className="text-slate-300 leading-relaxed">{finding.description}</p>
                          </div>
                        )}

                        {finding.suggestion && (
                          <div>
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Suggestion</p>
                            <p className="text-slate-300 leading-relaxed">{finding.suggestion}</p>
                          </div>
                        )}

                        <DiffView current={finding.code_snippet} suggested={finding.suggested_code} />

                        {finding.impact && (
                          <div>
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Impact</p>
                            <p className="text-slate-300 leading-relaxed">{finding.impact}</p>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}