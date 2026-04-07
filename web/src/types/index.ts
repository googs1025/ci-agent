// ──────────────────────────────────────────────────────────
// Shared primitive types
// ──────────────────────────────────────────────────────────

export type Severity = 'critical' | 'major' | 'minor' | 'info';

export type Dimension = 'efficiency' | 'security' | 'cost' | 'errors';

export type ReportStatus = 'pending' | 'running' | 'completed' | 'failed';

// ──────────────────────────────────────────────────────────
// Finding
// ──────────────────────────────────────────────────────────

export interface Finding {
  id: string;
  dimension: Dimension;
  severity: Severity;
  title: string;
  description: string;
  file_path?: string;
  line?: number;
  suggestion?: string;
  impact?: string;
}

// ──────────────────────────────────────────────────────────
// Report
// ──────────────────────────────────────────────────────────

export interface ReportListItem {
  id: string;
  repo_owner: string;
  repo_name: string;
  created_at: string; // ISO 8601
  status: ReportStatus;
  finding_count: number;
  duration_ms: number | null;
}

export interface Report extends ReportListItem {
  summary_md: string | null;
  full_report_json: Record<string, unknown> | null;
  error_message: string | null;
  findings: Finding[];
}

// ──────────────────────────────────────────────────────────
// Analyze request / response
// ──────────────────────────────────────────────────────────

export interface AnalyzeFilters {
  since?: string;
  until?: string;
  workflows?: string[];
  status?: string[];
  branches?: string[];
}

export interface AnalyzeRequest {
  repo: string;
  filters?: AnalyzeFilters;
}

export interface AnalyzeResponse {
  report_id: string;
  status: ReportStatus;
}

// ──────────────────────────────────────────────────────────
// Reports list
// ──────────────────────────────────────────────────────────

export interface ReportsListResponse {
  reports: ReportListItem[];
  total: number;
  page: number;
  limit: number;
}

// ──────────────────────────────────────────────────────────
// Dashboard
// ──────────────────────────────────────────────────────────

export interface SeverityDistribution {
  critical: number;
  major: number;
  minor: number;
  info: number;
  [key: string]: number;
}

export interface DimensionDistribution {
  efficiency: number;
  security: number;
  cost: number;
  errors: number;
  [key: string]: number;
}

export interface DashboardData {
  repo_count: number;
  analysis_count: number;
  severity_distribution: SeverityDistribution;
  dimension_distribution: DimensionDistribution;
  recent_reports: ReportListItem[];
}

// ──────────────────────────────────────────────────────────
// Repository
// ──────────────────────────────────────────────────────────

export interface Repository {
  id: string;
  owner: string;
  repo: string;
  url: string;
  last_analyzed_at: string | null;
}
