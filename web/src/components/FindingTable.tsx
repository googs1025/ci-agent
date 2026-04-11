'use client';

import { Fragment, useState } from 'react';
import type { Finding, Severity } from '@/types';
import SeverityBadge from './SeverityBadge';

interface FindingTableProps {
  findings: Finding[];
}

type SortField = 'severity' | 'title' | 'file_path';
type SortDir = 'asc' | 'desc';

const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  major: 1,
  minor: 2,
  info: 3,
};

function sortFindings(
  findings: Finding[],
  field: SortField,
  dir: SortDir,
): Finding[] {
  return [...findings].sort((a, b) => {
    let cmp = 0;
    if (field === 'severity') {
      cmp = (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9);
    } else if (field === 'title') {
      cmp = a.title.localeCompare(b.title);
    } else if (field === 'file_path') {
      cmp = (a.file_path ?? '').localeCompare(b.file_path ?? '');
    }
    return dir === 'asc' ? cmp : -cmp;
  });
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden="true"
      className={`inline-block ml-1 transition-opacity ${active ? 'opacity-100' : 'opacity-30'}`}
    >
      <path
        d={dir === 'asc' || !active ? 'M7 3L10 7H4L7 3Z' : 'M7 11L4 7H10L7 11Z'}
        fill="currentColor"
      />
    </svg>
  );
}

export default function FindingTable({ findings }: FindingTableProps) {
  const [sortField, setSortField] = useState<SortField>('severity');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  function handleSort(field: SortField) {
    if (field === sortField) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  }

  const sorted = sortFindings(findings, sortField, sortDir);

  if (findings.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">
        No findings in this dimension.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-surface-border">
      <table className="w-full text-sm" aria-label="Findings table">
        <thead>
          <tr className="border-b border-surface-border bg-surface-elevated">
            <th
              scope="col"
              className="px-4 py-3 text-left font-semibold text-slate-400 cursor-pointer select-none whitespace-nowrap w-28"
              onClick={() => handleSort('severity')}
              aria-sort={sortField === 'severity' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
            >
              Severity
              <SortIcon active={sortField === 'severity'} dir={sortDir} />
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-left font-semibold text-slate-400 cursor-pointer select-none"
              onClick={() => handleSort('title')}
              aria-sort={sortField === 'title' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
            >
              Title
              <SortIcon active={sortField === 'title'} dir={sortDir} />
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-left font-semibold text-slate-400 cursor-pointer select-none hidden md:table-cell"
              onClick={() => handleSort('file_path')}
              aria-sort={sortField === 'file_path' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
            >
              File
              <SortIcon active={sortField === 'file_path'} dir={sortDir} />
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-left font-semibold text-slate-400 hidden lg:table-cell"
            >
              Suggestion
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
                  onClick={() =>
                    setExpandedId(isExpanded ? null : finding.id)
                  }
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
                      {/* Expand chevron */}
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 14 14"
                        fill="none"
                        aria-hidden="true"
                        className={`shrink-0 text-slate-500 transition-transform duration-150 ${isExpanded ? 'rotate-90' : ''}`}
                      >
                        <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      {finding.title}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400 hidden md:table-cell">
                    {finding.file_path ? (
                      <>
                        {finding.file_path}
                        {finding.line != null && (
                          <span className="text-slate-600">:{finding.line}</span>
                        )}
                      </>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-400 hidden lg:table-cell max-w-xs truncate">
                    {finding.suggestion ?? <span className="text-slate-600">—</span>}
                  </td>
                </tr>

                {/* Expanded detail row */}
                {isExpanded && (
                  <tr
                    className="border-b border-surface-border bg-surface-elevated"
                  >
                    <td colSpan={4} className="px-6 py-4">
                      <div className="space-y-3 text-sm">
                        {finding.skill_name && (
                          <div>
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                              Source Skill
                            </p>
                            <code className="text-xs text-accent-purple font-mono">
                              {finding.skill_name}
                            </code>
                          </div>
                        )}

                        {finding.description && (
                          <div>
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                              Description
                            </p>
                            <p className="text-slate-300 leading-relaxed">
                              {finding.description}
                            </p>
                          </div>
                        )}

                        {finding.suggestion && (
                          <div>
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                              Suggestion
                            </p>
                            <p className="text-slate-300 leading-relaxed">
                              {finding.suggestion}
                            </p>
                          </div>
                        )}

                        {finding.code_snippet && (
                          <div>
                            <p className="text-xs font-semibold text-red-400 uppercase tracking-wide mb-1">
                              Current Code
                            </p>
                            <pre className="bg-red-500/5 border border-red-500/20 rounded-lg px-4 py-3 text-xs font-mono text-slate-300 overflow-x-auto whitespace-pre-wrap">
                              {finding.code_snippet}
                            </pre>
                          </div>
                        )}

                        {finding.suggested_code && (
                          <div>
                            <p className="text-xs font-semibold text-green-400 uppercase tracking-wide mb-1">
                              Suggested Code
                            </p>
                            <pre className="bg-green-500/5 border border-green-500/20 rounded-lg px-4 py-3 text-xs font-mono text-slate-300 overflow-x-auto whitespace-pre-wrap">
                              {finding.suggested_code}
                            </pre>
                          </div>
                        )}

                        {finding.impact && (
                          <div>
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                              Impact
                            </p>
                            <p className="text-slate-300 leading-relaxed">
                              {finding.impact}
                            </p>
                          </div>
                        )}

                        {finding.file_path && (
                          <div className="md:hidden">
                            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
                              File
                            </p>
                            <code className="text-xs text-accent-purple font-mono">
                              {finding.file_path}
                              {finding.line != null && `:${finding.line}`}
                            </code>
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
