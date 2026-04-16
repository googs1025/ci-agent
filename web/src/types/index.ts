// ──────────────────────────────────────────────────────────
// Shared primitive types
// ──────────────────────────────────────────────────────────

export type Severity = 'critical' | 'major' | 'minor' | 'info';

export type Dimension = string;

export type ReportStatus = 'pending' | 'running' | 'completed' | 'failed';

// ──────────────────────────────────────────────────────────
// Finding
// ──────────────────────────────────────────────────────────

export interface Finding {
  id: string;
  dimension: Dimension;
  skill_name?: string | null;
  severity: Severity;
  title: string;
  description: string;
  file_path?: string;
  line?: number;
  suggestion?: string;
  impact?: string;
  code_snippet?: string;
  suggested_code?: string;
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
  skills?: string[];  // dimension names; undefined = all
}

// ──────────────────────────────────────────────────────────
// Skills
// ──────────────────────────────────────────────────────────

export interface Skill {
  name: string;
  description: string;
  dimension: string;
  source: 'builtin' | 'user';
  enabled: boolean;
  priority: number;
  tools: string[];
  requires_data: string[];
  prompt?: string;
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
// Trends
// ──────────────────────────────────────────────────────────

export interface DailySeverityPoint {
  date: string;
  total: number;
  critical: number;
  major: number;
  minor: number;
  info: number;
}

export interface DimensionTrendPoint {
  date: string;
  efficiency: number;
  security: number;
  cost: number;
  errors: number;
}

export interface RepoComparisonItem {
  repo: string;
  total: number;
  critical: number;
  major: number;
  minor: number;
  info: number;
}

export interface TrendsData {
  daily_scores: DailySeverityPoint[];
  dimension_trends: DimensionTrendPoint[];
  repo_comparison: RepoComparisonItem[];
}

// ──────────────────────────────────────────────────────────
// Webhook
// ──────────────────────────────────────────────────────────

export interface WebhookStatus {
  enabled: boolean;
  secret_configured: boolean;
  webhook_url: string;
  supported_events: string[];
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

// ──────────────────────────────────────────────────────────
// Failure Triage (issue #35)
// ──────────────────────────────────────────────────────────

export type DiagnoseCategory =
  | 'flaky_test'
  | 'timeout'
  | 'dependency'
  | 'network'
  | 'resource_limit'
  | 'config'
  | 'build'
  | 'infra'
  | 'unknown';

export type DiagnoseConfidence = 'high' | 'medium' | 'low';

export type DiagnoseTier = 'default' | 'deep';

export interface DiagnoseRequest {
  repo: string;
  run_id: number;
  run_attempt?: number;
  tier?: DiagnoseTier;
}

export interface DiagnoseResponse {
  category: DiagnoseCategory;
  confidence: DiagnoseConfidence;
  root_cause: string;
  quick_fix: string | null;
  failing_step: string | null;
  error_excerpt: string;
  error_signature: string;
  workflow: string;
  model: string;
  cost_usd: number | null;
  cached: boolean;
  source: 'manual' | 'webhook_auto';
}

export interface DiagnoseSiblingRun {
  repo: string;
  run_id: number;
  run_attempt: number;
  workflow: string;
  failing_step: string | null;
  created_at: string;
}

export interface SignatureClusterResponse {
  signature: string;
  count: number;
  days: number;
  category: DiagnoseCategory | null;
  runs: DiagnoseSiblingRun[];
}

export interface FailedRunSummary {
  run_id: number;
  run_attempt: number;
  workflow: string;
  branch: string | null;
  event: string | null;
  created_at: string | null;
  html_url: string | null;
  actor: string | null;
}
