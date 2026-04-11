'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Renders the executive-summary markdown safely.
 *
 * Uses react-markdown + remark-gfm (GitHub flavored markdown). HTML in the
 * source is NOT rendered as HTML — it is shown as literal text. This matters
 * because LLM output sometimes contains placeholders like
 * `<FULL_LENGTH_COMMIT_SHA>` inside code blocks that would otherwise be
 * stripped by the browser.
 */
export default function SummaryMarkdown({ source }: { source: string }) {
  return (
    <div className="prose-dark">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{source}</ReactMarkdown>
    </div>
  );
}
