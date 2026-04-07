import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center">
      <span className="text-7xl font-black text-surface-elevated select-none">
        404
      </span>
      <h1 className="text-2xl font-bold text-white">Page not found</h1>
      <p className="text-slate-400 max-w-sm">
        The page or report you&apos;re looking for doesn&apos;t exist or may have
        been deleted.
      </p>
      <div className="flex gap-3 mt-4">
        <Link href="/" className="btn-primary">
          Dashboard
        </Link>
        <Link href="/reports" className="btn-secondary">
          Reports
        </Link>
      </div>
    </div>
  );
}
