'use client';

import { useCallback, useEffect, useState } from 'react';
import CategoryBadge from '@/components/CategoryBadge';
import { getSignatureCluster } from '@/lib/api';
import { interpolate, useLocale } from '@/lib/locale';
import type { DiagnoseResponse, SignatureClusterResponse } from '@/types';

interface FailureDiagnosisCardProps {
  diagnosis: DiagnoseResponse;
  /** Fires when the user requests a deep-tier re-run. */
  onDeepAnalysis?: () => void;
  /** True while a deep-tier request is in-flight. */
  deepLoading?: boolean;
}

function ConfidenceChip({ level }: { level: DiagnoseResponse['confidence'] }) {
  const { t } = useLocale();
  const colorMap = {
    high: 'text-green-400',
    medium: 'text-yellow-400',
    low: 'text-slate-400',
  } as const;
  return (
    <span className={`text-xs font-medium ${colorMap[level]}`}>
      {t(`diag.confidence.${level}`)}
    </span>
  );
}

function CopyButton({ text, className = '' }: { text: string; className?: string }) {
  const { t } = useLocale();
  const [copied, setCopied] = useState(false);
  const handle = useCallback(() => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);
  return (
    <button
      onClick={handle}
      className={`px-2 py-1 text-xs rounded bg-surface-elevated text-slate-400 hover:text-slate-200 transition-colors ${className}`}
    >
      {copied ? t('diag.result.copied') : t('diag.result.copy_fix')}
    </button>
  );
}

function SimilarErrors({ signature }: { signature: string }) {
  const { t } = useLocale();
  const [cluster, setCluster] = useState<SignatureClusterResponse | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getSignatureCluster(signature, 30);
        if (!cancelled) setCluster(data);
      } catch {
        // Cluster lookup is optional — fail silently.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [signature]);

  // Hide the section when the only match is the current run itself.
  if (!cluster || cluster.count <= 1) return null;

  return (
    <div className="border-t border-surface-border pt-4 mt-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500 mb-1">
            {interpolate(t('diag.result.similar'), { days: cluster.days })}
          </p>
          <p className="text-sm text-slate-200">
            {interpolate(t('diag.result.similar_count'), { count: cluster.count })}
          </p>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-accent-blue hover:underline"
        >
          {t('diag.result.view_cluster')}
        </button>
      </div>
      {expanded && (
        <ul className="mt-3 space-y-1.5 max-h-48 overflow-y-auto">
          {cluster.runs.map((r) => (
            <li
              key={`${r.repo}-${r.run_id}-${r.run_attempt}`}
              className="flex items-center justify-between text-xs text-slate-400 px-3 py-1.5 bg-surface-elevated rounded"
            >
              <span className="font-mono">
                {r.repo} · run #{r.run_id}
                {r.run_attempt > 1 && `.${r.run_attempt}`}
              </span>
              <span className="text-slate-500">
                {new Date(r.created_at).toLocaleDateString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function FailureDiagnosisCard({
  diagnosis,
  onDeepAnalysis,
  deepLoading,
}: FailureDiagnosisCardProps) {
  const { t } = useLocale();
  const [showExcerpt, setShowExcerpt] = useState(false);

  return (
    <div className="card space-y-5">
      {/* Header: category + confidence + cached tag */}
      <div className="flex flex-wrap items-center gap-3">
        <CategoryBadge category={diagnosis.category} />
        <ConfidenceChip level={diagnosis.confidence} />
        <span
          className={`px-2 py-0.5 text-xs rounded-full ${
            diagnosis.cached
              ? 'bg-slate-500/15 text-slate-400'
              : 'bg-green-400/15 text-green-400'
          }`}
        >
          {diagnosis.cached ? t('diag.result.cached') : t('diag.result.fresh')}
        </span>
      </div>

      {/* Root cause */}
      <div>
        <p className="text-xs uppercase tracking-wider text-slate-500 mb-1">
          {t('diag.result.root_cause')}
        </p>
        <p className="text-base text-slate-100 leading-relaxed">{diagnosis.root_cause}</p>
      </div>

      {/* Workflow + failing step */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="bg-surface-elevated rounded-lg p-3">
          <p className="text-xs uppercase tracking-wider text-slate-500 mb-1">
            {t('diag.result.workflow')}
          </p>
          <p className="text-sm text-slate-200 font-mono">{diagnosis.workflow}</p>
        </div>
        <div className="bg-surface-elevated rounded-lg p-3">
          <p className="text-xs uppercase tracking-wider text-slate-500 mb-1">
            {t('diag.result.failing_step')}
          </p>
          <p className="text-sm text-slate-200 font-mono">
            {diagnosis.failing_step ?? '—'}
          </p>
        </div>
      </div>

      {/* Quick fix */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs uppercase tracking-wider text-slate-500">
            {t('diag.result.quick_fix')}
          </p>
          {diagnosis.quick_fix && <CopyButton text={diagnosis.quick_fix} />}
        </div>
        {diagnosis.quick_fix ? (
          <pre className="bg-surface-elevated rounded-lg p-3 text-sm text-slate-200 font-mono whitespace-pre-wrap break-words">
            {diagnosis.quick_fix}
          </pre>
        ) : (
          <p className="text-sm text-slate-500 italic">
            {t('diag.result.no_quick_fix')}
          </p>
        )}
      </div>

      {/* Log excerpt (collapsible) */}
      <div>
        <button
          onClick={() => setShowExcerpt(!showExcerpt)}
          className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1"
        >
          <span className={`transition-transform ${showExcerpt ? 'rotate-90' : ''}`}>
            ▶
          </span>
          {showExcerpt ? t('diag.result.excerpt_hide') : t('diag.result.excerpt_show')}
        </button>
        {showExcerpt && (
          <pre className="mt-2 bg-surface-elevated rounded-lg p-3 text-xs text-slate-300 font-mono overflow-x-auto max-h-72 overflow-y-auto">
            {diagnosis.error_excerpt}
          </pre>
        )}
      </div>

      {/* Metadata row: model, cost, signature */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 pt-2 border-t border-surface-border">
        <span>
          {t('diag.result.model')}: <span className="text-slate-300 font-mono">{diagnosis.model}</span>
        </span>
        {diagnosis.cost_usd !== null && diagnosis.cost_usd !== undefined && (
          <span>
            {t('diag.result.cost')}:{' '}
            <span className="text-slate-300 font-mono">
              ${diagnosis.cost_usd.toFixed(4)}
            </span>
          </span>
        )}
        <span>
          {t('diag.result.signature')}:{' '}
          <span className="text-slate-300 font-mono">{diagnosis.error_signature}</span>
        </span>
      </div>

      {/* Deep analysis button */}
      {onDeepAnalysis && (
        <div className="pt-2">
          <button
            onClick={onDeepAnalysis}
            disabled={deepLoading}
            className="px-4 py-2 text-sm rounded-lg bg-accent-purple/15 text-accent-purple hover:bg-accent-purple/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deepLoading ? t('diag.form.submitting') : t('diag.result.deep_analysis')}
          </button>
        </div>
      )}

      <SimilarErrors signature={diagnosis.error_signature} />
    </div>
  );
}
