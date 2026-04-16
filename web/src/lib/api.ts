import type {
  AnalyzeRequest,
  AnalyzeResponse,
  DashboardData,
  DiagnoseRequest,
  DiagnoseResponse,
  Report,
  ReportsListResponse,
  Repository,
  SignatureClusterResponse,
  Skill,
  TrendsData,
  WebhookStatus,
} from '@/types';

// When running in the browser the Next.js rewrite proxies /api/* → FastAPI.
// During SSR or direct server usage we use the full URL.
const BASE_URL =
  typeof window === 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000')
    : '';

const API_KEY = process.env.NEXT_PUBLIC_CI_AGENT_API_KEY ?? '';

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${BASE_URL}${path}`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string> ?? {}),
  };

  if (API_KEY) {
    headers['Authorization'] = `Bearer ${API_KEY}`;
  }

  const res = await fetch(url, {
    cache: 'no-store',
    headers,
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
 * Fetch dashboard trend data for charts.
 */
export async function getTrends(
  days: number = 30,
  repo?: string,
): Promise<TrendsData> {
  const params = new URLSearchParams({ days: String(days) });
  if (repo) params.set('repo', repo);
  return request<TrendsData>(`/api/dashboard/trends?${params.toString()}`);
}

/**
 * Fetch the list of known repositories.
 */
export async function getRepositories(): Promise<Repository[]> {
  return request<Repository[]>('/api/repositories');
}

/**
 * Fetch the list of available analysis skills (builtin + user).
 */
export async function getSkills(): Promise<Skill[]> {
  return request<Skill[]>('/api/skills');
}

export type SkillSourceType = 'claude-code' | 'opencode' | 'path' | 'github';

export interface SkillImportRequest {
  source_type: SkillSourceType;
  source: string;
  dimension: string;
  requires_data?: string[];
  name_override?: string;
}

export interface SkillImportResponse {
  name: string;
  dimension: string;
  target_path: string;
  source_kind: string;
  warnings: string[];
}

export async function importSkill(
  req: SkillImportRequest,
): Promise<SkillImportResponse> {
  return request<SkillImportResponse>('/api/skills/import', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function deleteSkill(name: string): Promise<{ removed: string }> {
  return request<{ removed: string }>(`/api/skills/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

/**
 * Fetch webhook configuration status.
 */
export async function getWebhookStatus(): Promise<WebhookStatus> {
  return request<WebhookStatus>('/api/webhooks/status');
}

/**
 * Diagnose a single failed CI run (issue #35).
 * Returns a structured diagnosis; the backend handles caching + signature dedup.
 */
export async function diagnoseRun(
  req: DiagnoseRequest,
): Promise<DiagnoseResponse> {
  return request<DiagnoseResponse>('/api/ci-runs/diagnose', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/**
 * List all recent failures sharing the same error signature.
 */
export async function getSignatureCluster(
  signature: string,
  days: number = 30,
): Promise<SignatureClusterResponse> {
  const params = new URLSearchParams({ days: String(days) });
  return request<SignatureClusterResponse>(
    `/api/diagnoses/by-signature/${encodeURIComponent(signature)}?${params.toString()}`,
  );
}
