'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import SignOutButton from './signout-button';

export function Sidebar() {
  const pathname = usePathname();
  const isActive = (path: string) => pathname === path;

  return (
    <aside className="w-56 shrink-0 border-r border-border bg-surface flex flex-col py-6 px-4">
      <span className="font-semibold text-sm text-text tracking-tight px-2 mb-8">
        SaaS
      </span>

      <nav className="flex flex-col gap-0.5 flex-1">
        <Link
          href="/dashboard"
          className={`flex items-center gap-2.5 px-2 py-2 text-sm rounded transition-colors duration-100 ${
            isActive('/dashboard')
              ? 'text-accent font-medium border-l-2 border-accent pl-[7px] bg-surface-2'
              : 'text-text-2 hover:text-text hover:bg-surface-2 border-l-2 border-transparent pl-[7px]'
          }`}
        >
          <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
          </svg>
          Documents
        </Link>

        <Link
          href="/chat"
          className={`flex items-center gap-2.5 px-2 py-2 text-sm rounded transition-colors duration-100 ${
            isActive('/chat')
              ? 'text-accent font-medium border-l-2 border-accent pl-[7px] bg-surface-2'
              : 'text-text-2 hover:text-text hover:bg-surface-2 border-l-2 border-transparent pl-[7px]'
          }`}
        >
          <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
          </svg>
          AI Chat
        </Link>
      </nav>

      <div className="border-t border-border pt-4">
        <SignOutButton />
      </div>
    </aside>
  );
}