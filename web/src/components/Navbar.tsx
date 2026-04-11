'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const navLinks = [
  { href: '/', label: 'Dashboard' },
  { href: '/analyze', label: 'Analyze' },
  { href: '/reports', label: 'Reports' },
  { href: '/skills', label: 'Skills' },
];

export default function Navbar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 bg-surface-card border-b border-surface-border backdrop-blur-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo / brand */}
          <Link
            href="/"
            className="flex items-center gap-2.5 font-bold text-lg text-white hover:text-accent-blue transition-colors"
          >
            {/* Inline SVG pipeline icon */}
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
              className="text-accent-blue shrink-0"
            >
              <rect
                x="2"
                y="6"
                width="6"
                height="4"
                rx="1"
                fill="currentColor"
                opacity="0.8"
              />
              <rect
                x="9"
                y="6"
                width="6"
                height="4"
                rx="1"
                fill="currentColor"
              />
              <rect
                x="16"
                y="6"
                width="6"
                height="4"
                rx="1"
                fill="currentColor"
                opacity="0.6"
              />
              <path
                d="M8 8h1M15 8h1"
                stroke="currentColor"
                strokeWidth="1"
                opacity="0.5"
              />
              <rect
                x="6"
                y="14"
                width="6"
                height="4"
                rx="1"
                fill="currentColor"
                opacity="0.7"
              />
              <rect
                x="13"
                y="14"
                width="6"
                height="4"
                rx="1"
                fill="currentColor"
                opacity="0.5"
              />
              <path
                d="M5 10v4M12 10v4M19 10v4"
                stroke="currentColor"
                strokeWidth="1"
                opacity="0.3"
              />
            </svg>
            <span>CI Optimizer</span>
          </Link>

          {/* Navigation links */}
          <nav className="flex items-center gap-1" aria-label="Main navigation">
            {navLinks.map(({ href, label }) => {
              const isActive =
                href === '/' ? pathname === '/' : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={[
                    'px-4 py-2 rounded-lg text-sm font-medium transition-colors duration-150',
                    isActive
                      ? 'bg-surface-elevated text-accent-blue'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-surface-elevated',
                  ].join(' ')}
                  aria-current={isActive ? 'page' : undefined}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </header>
  );
}
