import type { Metadata } from 'next';
import Link from 'next/link';
import { getDashboard } from '@/lib/api';
import DashboardContent from '@/components/DashboardContent';

export const metadata: Metadata = { title: 'Dashboard' };

// Revalidate every 60 seconds
export const revalidate = 60;

export default async function DashboardPage() {
  let dashboard;
  try {
    dashboard = await getDashboard();
  } catch {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-slate-500">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <circle cx="24" cy="24" r="22" stroke="currentColor" strokeWidth="2" />
          <path d="M24 14v12M24 34v1" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
        </svg>
        <p className="text-lg font-medium text-slate-400">Could not reach the API server.</p>
        <p className="text-sm">Make sure the FastAPI backend is running at <code className="font-mono text-accent-purple">http://localhost:8000</code></p>
        <Link href="/analyze" className="btn-primary mt-2">
          Start an analysis anyway
        </Link>
      </div>
    );
  }

  return <DashboardContent dashboard={dashboard} />;
}