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