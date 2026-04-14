'use client';

import { useCallback, useEffect, useState } from 'react';
import { getWebhookStatus } from '@/lib/api';
import { useLocale } from '@/lib/locale';
import type { WebhookStatus } from '@/types';

function CopyButton({ text }: { text: string }) {
  const { t } = useLocale();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="px-2 py-1 text-xs rounded bg-surface-elevated text-slate-400 hover:text-slate-200 transition-colors"
    >
      {copied ? t('webhook.copied') : t('webhook.copy')}
    </button>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-green-400' : 'bg-yellow-400'}`}
    />
  );
}

export default function SettingsPage() {
  const { t } = useLocale();
  const [status, setStatus] = useState<WebhookStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await getWebhookStatus();
        setStatus(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const curlExample = status
    ? `curl -X POST ${status.webhook_url} \\
  -H "Content-Type: application/json" \\
  -d '{"repo": "owner/repo-name"}'`
    : '';

  const curlWithSignature = status
    ? `# With HMAC signature
SECRET="your-webhook-secret"
BODY='{"repo": "owner/repo-name"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | cut -d' ' -f2)

curl -X POST ${status.webhook_url} \\
  -H "Content-Type: application/json" \\
  -H "X-Hub-Signature-256: sha256=$SIG" \\
  -d "$BODY"`
    : '';

  return (
    <div className="space-y-8">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-white">{t('settings.title')}</h1>
        <p className="text-slate-400 text-sm mt-1">{t('settings.subtitle')}</p>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12 text-slate-400">
          <svg className="animate-spin h-5 w-5 mr-2" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading...
        </div>
      )}

      {error && (
        <div className="card border border-red-500/20 bg-red-500/5 text-red-400 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && status && (
        <>
          {/* Webhook status card */}
          <div className="card space-y-5">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="text-accent-blue">
                <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              {t('webhook.title')}
            </h2>

            {/* Status grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Enabled */}
              <div className="bg-surface-elevated rounded-lg p-4">
                <p className="text-xs text-slate-500 mb-1">{t('webhook.status')}</p>
                <p className="text-sm text-slate-200 flex items-center gap-2">
                  <StatusDot ok={status.enabled} />
                  {status.enabled ? t('webhook.enabled') : t('webhook.disabled')}
                </p>
              </div>

              {/* Secret */}
              <div className="bg-surface-elevated rounded-lg p-4">
                <p className="text-xs text-slate-500 mb-1">{t('webhook.secret')}</p>
                <p className="text-sm flex items-center gap-2">
                  <StatusDot ok={status.secret_configured} />
                  <span className={status.secret_configured ? 'text-green-400' : 'text-yellow-400'}>
                    {status.secret_configured
                      ? t('webhook.secret_configured')
                      : t('webhook.secret_not_configured')}
                  </span>
                </p>
              </div>

              {/* URL */}
              <div className="bg-surface-elevated rounded-lg p-4 sm:col-span-2">
                <p className="text-xs text-slate-500 mb-1">{t('webhook.url')}</p>
                <div className="flex items-center gap-2">
                  <code className="text-sm text-accent-blue font-mono flex-1 break-all">
                    {status.webhook_url}
                  </code>
                  <CopyButton text={status.webhook_url} />
                </div>
              </div>

              {/* Events */}
              <div className="bg-surface-elevated rounded-lg p-4 sm:col-span-2">
                <p className="text-xs text-slate-500 mb-1">{t('webhook.events')}</p>
                <div className="flex gap-2 mt-1">
                  {status.supported_events.map((evt) => (
                    <span
                      key={evt}
                      className="px-2 py-0.5 text-xs rounded bg-accent-blue/15 text-accent-blue font-mono"
                    >
                      {evt}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* GitHub setup guide */}
          <div className="card space-y-4">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="text-accent-purple">
                <path d="M12 2C6.477 2 2 6.477 2 12c0 4.42 2.865 8.17 6.839 9.49.5.092.682-.217.682-.482 0-.237-.008-.866-.013-1.7-2.782.604-3.369-1.34-3.369-1.34-.454-1.156-1.11-1.464-1.11-1.464-.908-.62.069-.607.069-.607 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.268 2.75 1.026A9.564 9.564 0 0112 6.844a9.59 9.59 0 012.504.337c1.909-1.294 2.747-1.026 2.747-1.026.546 1.377.203 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.167 22 16.418 22 12c0-5.523-4.477-10-10-10z" fill="currentColor"/>
              </svg>
              {t('webhook.setup_title')}
            </h2>
            <ol className="space-y-2 text-sm text-slate-300">
              <li>{t('webhook.setup_step1')}</li>
              <li>{t('webhook.setup_step2')}</li>
              <li>{t('webhook.setup_step3')}</li>
              <li>{t('webhook.setup_step4')}</li>
              <li>{t('webhook.setup_step5')}</li>
            </ol>
          </div>

          {/* curl examples */}
          <div className="card space-y-4">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="text-accent-green">
                <polyline points="4 17 10 11 4 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                <line x1="12" y1="19" x2="20" y2="19" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              </svg>
              {t('webhook.curl_title')}
            </h2>

            {/* Simple curl */}
            <div className="relative">
              <div className="absolute top-2 right-2">
                <CopyButton text={curlExample} />
              </div>
              <pre className="bg-surface-elevated rounded-lg p-4 text-sm text-slate-300 font-mono overflow-x-auto">
                {curlExample}
              </pre>
            </div>

            {/* With signature */}
            {status.secret_configured && (
              <div className="relative">
                <div className="absolute top-2 right-2">
                  <CopyButton text={curlWithSignature} />
                </div>
                <pre className="bg-surface-elevated rounded-lg p-4 text-sm text-slate-300 font-mono overflow-x-auto">
                  {curlWithSignature}
                </pre>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
