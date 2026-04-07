import type { Metadata } from 'next';
import Link from 'next/link';
import { getReports } from '@/lib/api';
import { format, parseISO } from 'date-fns';
import type { ReportListItem } from '@/types';

export const metadata: Metadata = { title: 'Reports' };

// Always fetch fresh data for this listing page
export const revalidate = 0;

interface PageProps {
  searchParams: { page?: string; repo?: string };
}

const PAGE_SIZE = 20;

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    completed: 'bg-green-500/15 text-green-400 ring-green-500/30',
    failed: 'bg-red-500/15 text-red-400 ring-red-500/30',
    running: 'bg-blue-500/15 text-blue-400 ring-blue-500/30',
    pending: 'bg-slate-500/15 text-slate-400 ring-slate-500/30',
  };
  return (
    <span
      className={`badge capitalize ring-1 ${cfg[status] ?? cfg.pending}`}
    >
      {status}
    </span>
  );
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default async function ReportsPage({ searchParams }: PageProps) {
  const page = Math.max(1, parseInt(searchParams.page ?? '1', 10));
  const repo = searchParams.repo;

  let data;
  try {
    data = await getReports(repo, page, PAGE_SIZE);
  } catch (err) {
    return (
      <div className="text-center py-20 text-slate-500">
        <p className="text-lg font-medium text-slate-400 mb-2">
          Failed to load reports
        </p>
        <p className="text-sm">
          {err instanceof Error ? err.message : 'Unknown error'}
        </p>
      </div>
    );
  }

  const { reports, total } = data;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function buildPageHref(p: number) {
    const params = new URLSearchParams();
    params.set('page', String(p));
    if (repo) params.set('repo', repo);
    return `/reports?${params.toString()}`;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Reports</h1>
          <p className="text-slate-400 text-sm mt-1">
            {total} {total === 1 ? 'analysis' : 'analyses'} found
          </p>
        </div>
        <Link href="/analyze" className="btn-primary">
          + New Analysis
        </Link>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        {reports.length === 0 ? (
          <div className="text-center py-20 text-slate-500">
            <p className="text-base font-medium text-slate-400 mb-2">No reports yet</p>
            <p className="text-sm mb-6">Run your first analysis to see results here.</p>
            <Link href="/analyze" className="btn-primary">
              Start an Analysis
            </Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Analysis reports">
              <thead>
                <tr className="border-b border-surface-border bg-surface-elevated">
                  <th scope="col" className="px-6 py-4 text-left font-semibold text-slate-400">
                    Repository
                  </th>
                  <th scope="col" className="px-4 py-4 text-left font-semibold text-slate-400 hidden sm:table-cell">
                    Date
                  </th>
                  <th scope="col" className="px-4 py-4 text-left font-semibold text-slate-400">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-4 text-right font-semibold text-slate-400">
                    Findings
                  </th>
                  <th scope="col" className="px-6 py-4 text-right font-semibold text-slate-400 hidden md:table-cell">
                    Duration
                  </th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r: ReportListItem) => (
                  <tr
                    key={r.id}
                    className="border-b border-surface-border last:border-0 table-row-hover group"
                  >
                    <td className="px-6 py-4">
                      <Link
                        href={`/reports/${r.id}`}
                        className="font-medium text-slate-200 group-hover:text-accent-blue transition-colors"
                      >
                        {r.repo_owner}/{r.repo_name}
                      </Link>
                    </td>
                    <td className="px-4 py-4 text-slate-400 whitespace-nowrap hidden sm:table-cell">
                      {format(parseISO(r.created_at), 'MMM d, yyyy · HH:mm')}
                    </td>
                    <td className="px-4 py-4">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-4 py-4 text-right font-mono text-slate-300">
                      {r.finding_count > 0 ? (
                        <span className="text-accent-yellow">{r.finding_count}</span>
                      ) : (
                        <span className="text-slate-500">0</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right text-slate-400 hidden md:table-cell">
                      {formatDuration(r.duration_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <nav
          className="flex items-center justify-center gap-2"
          aria-label="Pagination"
        >
          <Link
            href={buildPageHref(page - 1)}
            className={[
              'btn-secondary px-3',
              page <= 1 ? 'pointer-events-none opacity-40' : '',
            ].join(' ')}
            aria-disabled={page <= 1}
            aria-label="Previous page"
          >
            &lsaquo;
          </Link>

          {Array.from({ length: totalPages }, (_, i) => i + 1)
            .filter(
              (p) =>
                p === 1 || p === totalPages || Math.abs(p - page) <= 2,
            )
            .reduce<(number | '...')[]>((acc, p, idx, arr) => {
              if (idx > 0 && (arr[idx - 1] as number) + 1 < p) acc.push('...');
              acc.push(p);
              return acc;
            }, [])
            .map((p, idx) =>
              p === '...' ? (
                <span
                  key={`ellipsis-${idx}`}
                  className="px-3 py-2 text-slate-600 select-none"
                >
                  …
                </span>
              ) : (
                <Link
                  key={p}
                  href={buildPageHref(p)}
                  className={[
                    'px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                    p === page
                      ? 'bg-accent-blue text-white'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-surface-elevated',
                  ].join(' ')}
                  aria-current={p === page ? 'page' : undefined}
                >
                  {p}
                </Link>
              ),
            )}

          <Link
            href={buildPageHref(page + 1)}
            className={[
              'btn-secondary px-3',
              page >= totalPages ? 'pointer-events-none opacity-40' : '',
            ].join(' ')}
            aria-disabled={page >= totalPages}
            aria-label="Next page"
          >
            &rsaquo;
          </Link>
        </nav>
      )}
    </div>
  );
}
