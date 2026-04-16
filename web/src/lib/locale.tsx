'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

export type Lang = 'en' | 'zh';

interface LocaleCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
}

const LocaleContext = createContext<LocaleCtx>({
  lang: 'en',
  setLang: () => {},
  t: (k) => k,
});

// ──────────────────────────────────────────────────────────
// Translation dictionary
// ──────────────────────────────────────────────────────────

const dict: Record<Lang, Record<string, string>> = {
  en: {
    // Navbar
    'nav.dashboard': 'Dashboard',
    'nav.analyze': 'Analyze',
    'nav.reports': 'Reports',
    'nav.skills': 'Skills',

    // Dashboard page
    'dash.title': 'Dashboard',
    'dash.subtitle': 'Overview of your CI pipeline health',
    'dash.new_analysis': '+ New Analysis',
    'dash.repositories': 'Repositories',
    'dash.total_analyses': 'Total Analyses',
    'dash.total_findings': 'Total Findings',
    'dash.critical': 'critical',
    'dash.severity_dist': 'Severity Distribution',
    'dash.dimension_dist': 'Dimension Distribution',
    'dash.recent_reports': 'Recent Reports',
    'dash.view_all': 'View all',
    'dash.no_analyses': 'No analyses yet.',
    'dash.start_one': 'Start one now',
    'dash.api_error': 'Could not reach the API server.',
    'dash.api_hint': 'Make sure the FastAPI backend is running at',
    'dash.start_anyway': 'Start an analysis anyway',

    // Table headers
    'table.repository': 'Repository',
    'table.date': 'Date',
    'table.status': 'Status',
    'table.findings': 'Findings',
    'table.duration': 'Duration',

    // Severity & Dimension labels
    'sev.critical': 'critical',
    'sev.major': 'major',
    'sev.minor': 'minor',
    'sev.info': 'info',
    'dim.efficiency': 'efficiency',
    'dim.security': 'security',
    'dim.cost': 'cost',
    'dim.errors': 'errors',

    // Trend charts
    'trend.title': 'Trend Analysis',
    'trend.insights': 'Insights',
    'trend.finding_trend': 'Finding Trend',
    'trend.dimension_trend': 'Dimension Trend',
    'trend.repo_comparison': 'Repository Comparison',
    'trend.loading': 'Loading trends...',
    'trend.empty': 'No trend data available yet.',
    'trend.empty_hint': 'Run some analyses to see trends here.',
    'trend.total': 'Total',
    'trend.critical': 'Critical',
    'trend.major': 'Major',
    'trend.minor': 'Minor',
    'trend.info': 'Info',
    'trend.efficiency': 'Efficiency',
    'trend.security': 'Security',
    'trend.cost': 'Cost',
    'trend.errors': 'Errors',

    // Insight templates
    'insight.increased': 'Findings increased from {from} to {to} over the past {days} days — review recent changes.',
    'insight.decreased': 'Findings decreased from {from} to {to} over the past {days} days — good progress!',
    'insight.stable': 'Finding count remained stable at {count} over the past {days} days.',
    'insight.critical_found': '{count} critical finding(s) detected — prioritize fixing these first.',
    'insight.no_critical': 'No critical findings in this period — keep it up!',
    'insight.top_dimension': '{dim} accounts for {pct}% of all findings — the top area to improve.',
    'insight.worst_repo': '{repo} has the most findings ({count}) — consider a focused review.',

    // Settings / Webhook
    'nav.settings': 'Settings',
    'settings.title': 'Settings',
    'settings.subtitle': 'Webhook configuration and integration',
    'webhook.title': 'Webhook Configuration',
    'webhook.status': 'Status',
    'webhook.enabled': 'Enabled',
    'webhook.disabled': 'Disabled',
    'webhook.secret': 'HMAC Secret',
    'webhook.secret_configured': 'Configured',
    'webhook.secret_not_configured': 'Not configured (all requests accepted)',
    'webhook.url': 'Webhook URL',
    'webhook.events': 'Supported Events',
    'webhook.setup_title': 'GitHub Setup Guide',
    'webhook.setup_step1': '1. Go to your GitHub repository Settings → Webhooks → Add webhook',
    'webhook.setup_step2': '2. Set the Payload URL to the webhook URL shown above',
    'webhook.setup_step3': '3. Set Content type to application/json',
    'webhook.setup_step4': '4. Set the Secret to match your WEBHOOK_SECRET env var',
    'webhook.setup_step5': '5. Select "Workflow runs" under events',
    'webhook.curl_title': 'Manual Trigger (curl)',
    'webhook.copy': 'Copy',
    'webhook.copied': 'Copied!',

    // Diagnose page
    'nav.diagnose': 'Diagnose',
    'diag.title': 'CI Failure Diagnose',
    'diag.subtitle': 'AI-powered root cause analysis for a single failed CI run',
    'diag.form.repo': 'Repository',
    'diag.form.repo_placeholder': 'owner/repo  or  GitHub Actions run URL',
    'diag.form.run_id': 'Run ID',
    'diag.form.run_id_placeholder': 'GitHub workflow_run.id',
    'diag.form.run_attempt': 'Run Attempt',
    'diag.form.tier': 'Analysis Tier',
    'diag.form.tier_default': 'Default (fast + cheap)',
    'diag.form.tier_deep': 'Deep (more accurate)',
    'diag.form.submit': 'Find Failures',
    'diag.form.submitting': 'Loading...',
    'diag.form.help': 'Enter owner/repo to browse recent failures, or paste a run URL for direct diagnosis.',
    'diag.form.advanced': 'Advanced: enter run ID manually',
    'diag.form.advanced_close': 'Hide advanced',

    // Failure picker
    'diag.picker.title': 'Recent Failures',
    'diag.picker.subtitle': '{count} failed runs grouped into {groups} workflow(s)',
    'diag.picker.empty': 'No recent failures found — this repo is healthy!',
    'diag.picker.diagnose': 'Diagnose',
    'diag.picker.diagnosing': 'Diagnosing...',
    'diag.picker.loading': 'Loading recent failures...',
    'diag.picker.th_workflow': 'Workflow',
    'diag.picker.th_branch': 'Branch',
    'diag.picker.th_actor': 'Triggered by',
    'diag.picker.th_time': 'Time',
    'diag.picker.th_action': '',
    'diag.picker.attempt': 'attempt {n}',
    'diag.picker.change_repo': '← Change repo',
    'diag.picker.group_count': '{count} failures',
    'diag.picker.expand_all': 'Expand all',
    'diag.picker.collapse_all': 'Collapse all',
    'diag.picker.latest': 'Latest: {time}',
    'diag.picker.diagnose_latest': 'Diagnose latest',

    'diag.result.root_cause': 'Root Cause',
    'diag.result.quick_fix': 'Quick Fix',
    'diag.result.failing_step': 'Failing Step',
    'diag.result.workflow': 'Workflow',
    'diag.result.excerpt': 'Error Excerpt',
    'diag.result.excerpt_show': 'Show log excerpt',
    'diag.result.excerpt_hide': 'Hide log excerpt',
    'diag.result.model': 'Model',
    'diag.result.cost': 'Cost',
    'diag.result.signature': 'Signature',
    'diag.result.cached': 'Cached',
    'diag.result.fresh': 'Fresh',
    'diag.result.deep_analysis': 'Re-run with Deep Analysis',
    'diag.result.copy_fix': 'Copy fix',
    'diag.result.copied': 'Copied!',
    'diag.result.similar': 'Similar errors in the last {days} days',
    'diag.result.similar_count': '{count} related failures',
    'diag.result.view_cluster': 'View all →',
    'diag.result.no_quick_fix': 'No quick fix suggested',

    'diag.confidence.high': 'High confidence',
    'diag.confidence.medium': 'Medium confidence',
    'diag.confidence.low': 'Low confidence',

    'diag.cat.flaky_test': 'Flaky Test',
    'diag.cat.timeout': 'Timeout',
    'diag.cat.dependency': 'Dependency',
    'diag.cat.network': 'Network',
    'diag.cat.resource_limit': 'Resource Limit',
    'diag.cat.config': 'Configuration',
    'diag.cat.build': 'Build Failure',
    'diag.cat.infra': 'Infrastructure',
    'diag.cat.unknown': 'Unknown',

    'diag.error.no_failures': 'This run has no failed jobs — nothing to diagnose.',
    'diag.error.not_found': 'Run not found. Check the repo and run ID.',
    'diag.error.rate_limit': 'GitHub API rate limit — try again later.',
    'diag.error.llm': 'Diagnosis failed — the AI model returned an error.',
    'diag.error.generic': 'Something went wrong.',

    'diag.empty.title': 'Diagnose a failed CI run',
    'diag.empty.hint': 'Enter a repository and workflow run ID above to begin.',
  },

  zh: {
    // Navbar
    'nav.dashboard': '仪表盘',
    'nav.analyze': '分析',
    'nav.reports': '报告',
    'nav.skills': '技能',

    // Dashboard page
    'dash.title': '仪表盘',
    'dash.subtitle': 'CI 流水线健康状况总览',
    'dash.new_analysis': '+ 新建分析',
    'dash.repositories': '仓库',
    'dash.total_analyses': '总分析次数',
    'dash.total_findings': '总发现数',
    'dash.critical': '严重',
    'dash.severity_dist': '严重程度分布',
    'dash.dimension_dist': '维度分布',
    'dash.recent_reports': '最近报告',
    'dash.view_all': '查看全部',
    'dash.no_analyses': '暂无分析记录。',
    'dash.start_one': '立即开始',
    'dash.api_error': '无法连接 API 服务。',
    'dash.api_hint': '请确认 FastAPI 后端正在运行于',
    'dash.start_anyway': '仍然开始分析',

    // Table headers
    'table.repository': '仓库',
    'table.date': '日期',
    'table.status': '状态',
    'table.findings': '发现',
    'table.duration': '耗时',

    // Severity & Dimension labels
    'sev.critical': '严重',
    'sev.major': '重要',
    'sev.minor': '轻微',
    'sev.info': '信息',
    'dim.efficiency': '效率',
    'dim.security': '安全',
    'dim.cost': '成本',
    'dim.errors': '错误',

    // Trend charts
    'trend.title': '趋势分析',
    'trend.insights': '分析洞察',
    'trend.finding_trend': '发现趋势',
    'trend.dimension_trend': '维度趋势',
    'trend.repo_comparison': '仓库对比',
    'trend.loading': '加载趋势数据...',
    'trend.empty': '暂无趋势数据。',
    'trend.empty_hint': '运行一些分析后即可查看趋势。',
    'trend.total': '总计',
    'trend.critical': '严重',
    'trend.major': '重要',
    'trend.minor': '轻微',
    'trend.info': '信息',
    'trend.efficiency': '效率',
    'trend.security': '安全',
    'trend.cost': '成本',
    'trend.errors': '错误',

    // Insight templates
    'insight.increased': '过去 {days} 天内发现数从 {from} 增加到 {to} — 建议审查近期变更。',
    'insight.decreased': '过去 {days} 天内发现数从 {from} 减少到 {to} — 进展良好！',
    'insight.stable': '过去 {days} 天内发现数稳定在 {count} 个。',
    'insight.critical_found': '检测到 {count} 个严重问题 — 建议优先修复。',
    'insight.no_critical': '本期无严重问题 — 继续保持！',
    'insight.top_dimension': '{dim} 占所有发现的 {pct}% — 最需改进的领域。',
    'insight.worst_repo': '{repo} 的发现最多（{count} 个）— 建议重点审查。',

    // Settings / Webhook
    'nav.settings': '设置',
    'settings.title': '设置',
    'settings.subtitle': 'Webhook 配置与集成',
    'webhook.title': 'Webhook 配置',
    'webhook.status': '状态',
    'webhook.enabled': '已启用',
    'webhook.disabled': '已禁用',
    'webhook.secret': 'HMAC 密钥',
    'webhook.secret_configured': '已配置',
    'webhook.secret_not_configured': '未配置（接受所有请求）',
    'webhook.url': 'Webhook 地址',
    'webhook.events': '支持的事件',
    'webhook.setup_title': 'GitHub 配置指南',
    'webhook.setup_step1': '1. 进入 GitHub 仓库 Settings → Webhooks → Add webhook',
    'webhook.setup_step2': '2. 将 Payload URL 设为上方显示的 Webhook 地址',
    'webhook.setup_step3': '3. Content type 选择 application/json',
    'webhook.setup_step4': '4. Secret 填写与 WEBHOOK_SECRET 环境变量一致的值',
    'webhook.setup_step5': '5. 在事件中勾选 "Workflow runs"',
    'webhook.curl_title': '手动触发（curl）',
    'webhook.copy': '复制',
    'webhook.copied': '已复制！',

    // Diagnose page
    'nav.diagnose': '诊断',
    'diag.title': 'CI 失败诊断',
    'diag.subtitle': '针对单次失败运行的 AI 根因分析',
    'diag.form.repo': '仓库',
    'diag.form.repo_placeholder': 'owner/repo  或  GitHub Actions run URL',
    'diag.form.run_id': 'Run ID',
    'diag.form.run_id_placeholder': 'GitHub workflow_run.id',
    'diag.form.run_attempt': '重试次数',
    'diag.form.tier': '分析层级',
    'diag.form.tier_default': '默认（快速低成本）',
    'diag.form.tier_deep': '深度（更准确）',
    'diag.form.submit': '查找失败',
    'diag.form.submitting': '加载中...',
    'diag.form.help': '输入 owner/repo 浏览最近的失败运行，或直接粘贴 run URL 立即诊断。',
    'diag.form.advanced': '高级：手动输入 run ID',
    'diag.form.advanced_close': '收起高级选项',

    // Failure picker
    'diag.picker.title': '最近的失败',
    'diag.picker.subtitle': '{count} 次失败 · 按 {groups} 个工作流分组',
    'diag.picker.empty': '最近没有失败运行 — 这个仓库很健康！',
    'diag.picker.diagnose': '诊断',
    'diag.picker.diagnosing': '诊断中...',
    'diag.picker.loading': '加载中...',
    'diag.picker.th_workflow': '工作流',
    'diag.picker.th_branch': '分支',
    'diag.picker.th_actor': '触发者',
    'diag.picker.th_time': '时间',
    'diag.picker.th_action': '',
    'diag.picker.attempt': '第 {n} 次重试',
    'diag.picker.change_repo': '← 换一个仓库',
    'diag.picker.group_count': '{count} 次失败',
    'diag.picker.expand_all': '全部展开',
    'diag.picker.collapse_all': '全部收起',
    'diag.picker.latest': '最近: {time}',
    'diag.picker.diagnose_latest': '诊断最新',

    'diag.result.root_cause': '根本原因',
    'diag.result.quick_fix': '快速修复',
    'diag.result.failing_step': '失败步骤',
    'diag.result.workflow': '工作流',
    'diag.result.excerpt': '错误日志片段',
    'diag.result.excerpt_show': '展开日志片段',
    'diag.result.excerpt_hide': '收起日志片段',
    'diag.result.model': '模型',
    'diag.result.cost': '成本',
    'diag.result.signature': '错误签名',
    'diag.result.cached': '命中缓存',
    'diag.result.fresh': '新诊断',
    'diag.result.deep_analysis': '使用深度分析重跑',
    'diag.result.copy_fix': '复制修复',
    'diag.result.copied': '已复制！',
    'diag.result.similar': '近 {days} 天内的相似错误',
    'diag.result.similar_count': '{count} 次相关失败',
    'diag.result.view_cluster': '查看全部 →',
    'diag.result.no_quick_fix': '暂无快速修复建议',

    'diag.confidence.high': '高置信度',
    'diag.confidence.medium': '中等置信度',
    'diag.confidence.low': '低置信度',

    'diag.cat.flaky_test': '不稳定测试',
    'diag.cat.timeout': '超时',
    'diag.cat.dependency': '依赖问题',
    'diag.cat.network': '网络问题',
    'diag.cat.resource_limit': '资源限制',
    'diag.cat.config': '配置问题',
    'diag.cat.build': '构建失败',
    'diag.cat.infra': '基础设施',
    'diag.cat.unknown': '未知',

    'diag.error.no_failures': '该 run 没有失败的 job — 无需诊断。',
    'diag.error.not_found': '找不到该 run，请检查仓库和 run ID。',
    'diag.error.rate_limit': 'GitHub API 限流 — 请稍后再试。',
    'diag.error.llm': '诊断失败 — AI 模型返回错误。',
    'diag.error.generic': '出现问题。',

    'diag.empty.title': '诊断失败的 CI 运行',
    'diag.empty.hint': '在上方输入仓库和 run ID 以开始诊断。',
  },
};

// ──────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────

/** Simple template interpolation: "Hello {name}" + {name:"World"} → "Hello World" */
export function interpolate(
  template: string,
  vars: Record<string, string | number>,
): string {
  return template.replace(/\{(\w+)\}/g, (_, key) =>
    vars[key] !== undefined ? String(vars[key]) : `{${key}}`,
  );
}

// ──────────────────────────────────────────────────────────
// Provider
// ──────────────────────────────────────────────────────────

const STORAGE_KEY = 'ci-agent-lang';

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>('en');

  // Hydrate from localStorage
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'en' || stored === 'zh') {
      setLangState(stored);
    }
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    localStorage.setItem(STORAGE_KEY, l);
  }, []);

  const t = useCallback(
    (key: string) => dict[lang][key] ?? dict.en[key] ?? key,
    [lang],
  );

  return (
    <LocaleContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale() {
  return useContext(LocaleContext);
}