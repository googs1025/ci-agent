import type {
  AnalyzeRequest,
  AnalyzeResponse,
  DashboardData,
  Report,
  ReportsListResponse,
  Repository,
} from '@/types';

// When running in the browser the Next.js rewrite proxies /api/* → FastAPI.
// During SSR or direct server usage we use the full URL.
const BASE_URL =
  typeof window === 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000')
    : '';

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${BASE_URL}${path}`;

  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
    ...options,
  });

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body.detail ?? body.message ?? message;
    } catch {
      // ignore parse errors
    }
    throw new Error(message);
  }

  return res.json() as Promise<T>;
}

// ──────────────────────────────────────────────────────────
// API functions
// ──────────────────────────────────────────────────────────

/**
 * Kick off a new analysis for a repository.
 */
export async function analyzeRepo(
  payload: AnalyzeRequest,
): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>('/api/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Fetch paginated list of reports, optionally filtered by repo.
 */
export async function getReports(
  repo?: string,
  page = 1,
  limit = 20,
): Promise<ReportsListResponse> {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (repo) params.set('repo', repo);
  return request<ReportsListResponse>(`/api/reports?${params.toString()}`);
}

/**
 * Fetch a single report by ID (includes findings).
 */
export async function getReport(id: string): Promise<Report> {
  return request<Report>(`/api/reports/${encodeURIComponent(id)}`);
}

/**
 * Fetch dashboard summary data.
 */
export async function getDashboard(): Promise<DashboardData> {
  return request<DashboardData>('/api/dashboard');
}

/**
 * Fetch the list of known repositories.
 */
export async function getRepositories(): Promise<Repository[]> {
  return request<Repository[]>('/api/repositories');
}
