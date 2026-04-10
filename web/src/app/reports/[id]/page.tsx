import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getReport } from '@/lib/api';
import { format, parseISO } from 'date-fns';
import type { Dimension, Finding, Severity } from '@/types';
import FindingTable from '@/components/FindingTable';
import SeverityBadge from '@/components/SeverityBadge';
import ReportTabs from './ReportTabs';

// ──────────────────────────────────────────────────────────
// Metadata
// ──────────────────────────────────────────────────────────

export async function generateMetadata({
  params,
}: {
  params: { id: string };
}): Promise<Metadata> {
  try {
    const report = await getReport(params.id);
    return {
      title: `${report.repo_owner}/${report.repo_name} — Report`,
    };
  } catch {
    return { title: 'Report' };
  }
}

// ──────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────

function formatDuration(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    completed: 'bg-green-500/15 text-green-400',
    failed: 'bg-red-500/15 text-red-400',
    running: 'bg-blue-500/15 text-blue-400',
    pending: 'bg-slate-500/15 text-slate-400',
  };
  return (
    <span className={`badge capitalize ${cfg[status] ?? cfg.pending}`}>
      {status}
    </span>
  );
}

/**
 * Lightweight markdown → HTML converter for the summary section.
 *
 * Key correctness properties:
 *  1. HTML-escapes all user content so things like `<FULL_LENGTH_COMMIT_SHA>`
 *     are NOT interpreted as HTML tags.
 *  2. Code blocks are extracted FIRST as placeholders so the line-wrapping
 *     logic does not insert <p> tags inside <pre><code> blocks (which would
 *     create massive vertical gaps).
 *  3. Tables (GitHub flavored) are converted to <table>.
 */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderMarkdown(md: string): string {
  // 1. Extract fenced code blocks first to protect them from later transforms.
  const codeBlocks: string[] = [];
  const CODE_PLACEHOLDER = (i: number) => `\u0000CODEBLOCK${i}\u0000`;
  let working = md.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) => {
    const escaped = escapeHtml(code.replace(/\n$/, ''));
    codeBlocks.push(`<pre><code>${escaped}</code></pre>`);
    return CODE_PLACEHOLDER(codeBlocks.length - 1);
  });

  // 2. Extract inline code (single backtick) similarly.
  const inlineCodes: string[] = [];
  const INLINE_PLACEHOLDER = (i: number) => `\u0000INLINE${i}\u0000`;
  working = working.replace(/`([^`\n]+)`/g, (_m, code) => {
    inlineCodes.push(`<code>${escapeHtml(code)}</code>`);
    return INLINE_PLACEHOLDER(inlineCodes.length - 1);
  });

  // 3. HTML-escape everything else (placeholders contain only \u0000 + ASCII so they survive).
  working = escapeHtml(working);

  // 4. GitHub-flavored tables. Detect by looking for header line + separator line.
  working = working.replace(
    /(^\|.+\|\n\|[ \-:|]+\|\n(?:\|.*\|\n?)+)/gm,
    (block) => {
      const lines = block.trim().split('\n');
      const header = lines[0];
      const rows = lines.slice(2);
      const headerCells = header.split('|').slice(1, -1).map((c) => c.trim());
      const headerHtml =
        '<thead><tr>' +
        headerCells.map((c) => `<th>${c}</th>`).join('') +
        '</tr></thead>';
      const rowsHtml =
        '<tbody>' +
        rows
          .map((row) => {
            const cells = row.split('|').slice(1, -1).map((c) => c.trim());
            return '<tr>' + cells.map((c) => `<td>${c}</td>`).join('') + '</tr>';
          })
          .join('') +
        '</tbody>';
      return `<table>${headerHtml}${rowsHtml}</table>`;
    },
  );

  // 5. Headings.
  working = working
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // 6. Bold and italic. Process bold first to avoid * confusion.
  working = working
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');

  // 7. Horizontal rule.
  working = working.replace(/^---$/gm, '<hr>');

  // 8. List items.
  working = working
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Wrap consecutive <li> blocks in <ul>.
  working = working.replace(
    /(?:<li>[\s\S]*?<\/li>\n?)+/g,
    (match) => `<ul>${match}</ul>`,
  );

  // 9. Wrap remaining text lines in <p>. Skip:
  //    - empty lines
  //    - lines that start with a block-level tag (already handled)
  //    - lines that start with a code-block placeholder
  working = working
    .split('\n')
    .map((line) => {
      const trimmed = line.trim();
      if (!trimmed) return '';
      if (trimmed.startsWith('<')) return line;
      if (trimmed.startsWith('\u0000CODEBLOCK')) return line;
      return `<p>${line}</p>`;
    })
    .join('\n');

  // 10. Restore code block placeholders.
  working = working.replace(/\u0000CODEBLOCK(\d+)\u0000/g, (_m, i) => codeBlocks[Number(i)]);
  working = working.replace(/\u0000INLINE(\d+)\u0000/g, (_m, i) => inlineCodes[Number(i)]);

  return working;
}

function SeverityCount({
  severity,
  count,
}: {
  severity: Severity;
  count: number;
}) {
  if (count === 0) return null;
  return (
    <div className="flex items-center gap-1.5">
      <SeverityBadge severity={severity} dotOnly />
      <span className="text-sm font-semibold text-slate-300">{count}</span>
      <span className="text-xs text-slate-500 capitalize">{severity}</span>
    </div>
  );
}

// ──────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────

export default async function ReportDetailPage({
  params,
}: {
  params: { id: string };
}) {
  let report;
  try {
    report = await getReport(params.id);
  } catch {
    notFound();
  }

  const {
    repo_owner,
    repo_name,
    created_at,
    status,
    duration_ms,
    summary_md,
    error_message,
    findings,
  } = report;

  // Count by severity
  const sevCounts = findings.reduce(
    (acc, f) => {
      acc[f.severity] = (acc[f.severity] ?? 0) + 1;
      return acc;
    },
    {} as Record<Severity, number>,
  );

  // Group by dimension
  const byDimension = findings.reduce(
    (acc, f) => {
      (acc[f.dimension] ??= []).push(f);
      return acc;
    },
    {} as Record<Dimension, Finding[]>,
  );

  // Build dimensions dynamically from findings
  const dimensionKeys = Array.from(new Set(findings.map((f) => f.dimension)));
  // Keep known dimensions in standard order, append unknown ones
  const KNOWN_ORDER: string[] = ['efficiency', 'security', 'cost', 'errors'];
  const ordered = [
    ...KNOWN_ORDER.filter((k) => dimensionKeys.includes(k)),
    ...dimensionKeys.filter((k) => !KNOWN_ORDER.includes(k)),
  ];
  // Ensure at least the known dimensions are shown even if no findings (for empty state)
  const dimensionsToShow = ordered.length > 0 ? ordered : KNOWN_ORDER;
  const dimensions: { key: Dimension; label: string; count: number }[] = dimensionsToShow.map((key) => ({
    key,
    label: key.charAt(0).toUpperCase() + key.slice(1),
    count: (byDimension[key] ?? []).length,
  }));

  return (
    <div className="space-y-8">
      {/* Back link */}
      <Link
        href="/reports"
        className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M10 12L6 8l4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        All Reports
      </Link>

      {/* ── Header card ── */}
      <div className="card">
        <div className="flex flex-col sm:flex-row sm:items-start gap-4">
          {/* Title block */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-bold text-white truncate">
                {repo_owner}/{repo_name}
              </h1>
              <StatusBadge status={status} />
            </div>
            <p className="text-sm text-slate-400 mt-1">
              Analyzed {format(parseISO(created_at), "MMM d, yyyy 'at' HH:mm")}
              {duration_ms != null && (
                <> &middot; {formatDuration(duration_ms)}</>
              )}
            </p>
          </div>

          {/* Severity counts */}
          <div className="flex items-center gap-4 flex-wrap">
            {(['critical', 'major', 'minor', 'info'] as Severity[]).map((sev) => (
              <SeverityCount
                key={sev}
                severity={sev}
                count={sevCounts[sev] ?? 0}
              />
            ))}
            {findings.length === 0 && (
              <span className="text-sm text-slate-500">No findings</span>
            )}
          </div>
        </div>
      </div>

      {/* ── Error message ── */}
      {status === 'failed' && error_message && (
        <div
          role="alert"
          className="flex items-start gap-3 bg-red-500/10 border border-red-500/25 rounded-xl px-5 py-4 text-sm text-red-400"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0 mt-0.5">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
            <path d="M12 8v5M12 15v1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <div>
            <p className="font-semibold text-red-300 mb-0.5">Analysis failed</p>
            <p>{error_message}</p>
          </div>
        </div>
      )}

      {/* ── Executive summary ── */}
      {summary_md && (
        <section aria-labelledby="summary-heading">
          <div className="card">
            <h2
              id="summary-heading"
              className="font-semibold text-slate-200 text-base mb-4"
            >
              Executive Summary
            </h2>
            <div
              className="prose-dark"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(summary_md) }}
            />
          </div>
        </section>
      )}

      {/* ── Dimension tabs ── */}
      {findings.length > 0 && (
        <section aria-labelledby="findings-heading">
          <h2
            id="findings-heading"
            className="font-semibold text-slate-200 text-base mb-4"
          >
            Findings by Dimension
          </h2>
          <ReportTabs dimensions={dimensions} byDimension={byDimension} />
        </section>
      )}

      {status === 'completed' && findings.length === 0 && !error_message && (
        <div className="card text-center py-12 text-slate-500">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true" className="mx-auto mb-3 text-green-500">
            <circle cx="20" cy="20" r="18" stroke="currentColor" strokeWidth="2" />
            <path d="M12 20l6 6 10-12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <p className="font-medium text-slate-300">No findings — your pipeline looks great!</p>
        </div>
      )}
    </div>
  );
}
