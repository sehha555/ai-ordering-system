'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { Menu, X, ShoppingBag, Store, BarChart3, Activity } from 'lucide-react';

const NAV_ITEMS = [
  { href: '/admin/dashboard', label: '效能監控', Icon: BarChart3 },
  { href: '/admin/monitor', label: 'Pipeline Monitor', Icon: Activity },
  { href: '/admin/orders', label: '訂單列表', Icon: ShoppingBag },
  { href: '/admin/menu', label: '菜單管理', Icon: Store },
];

const PAGE_TITLE: Record<string, string> = {
  '/admin/dashboard': '效能監控',
  '/admin/monitor': 'Pipeline Monitor',
  '/admin/orders': '訂單列表',
  '/admin/menu': '菜單管理',
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const title = PAGE_TITLE[pathname] ?? '後台管理';

  return (
    <>
      {/* ─── Top Bar ─── */}
      <header
        className="sticky top-0 z-30 flex items-center px-4 gap-3"
        style={{
          height: '52px',
          backgroundColor: '#729DAD',
          boxShadow: '0 2px 8px rgba(90,132,148,0.25)',
        }}
      >
        <button
          onClick={() => setOpen(true)}
          className="flex items-center justify-center rounded-lg"
          style={{ width: 36, height: 36, color: '#ffffff' }}
          aria-label="開啟選單"
        >
          <Menu size={22} />
        </button>
        <span className="flex-1 text-center text-base font-bold" style={{ color: '#ffffff' }}>
          {title}
        </span>
        {/* 右側留空，維持置中效果 */}
        <div style={{ width: 36 }} />
      </header>

      {/* ─── Drawer Overlay ─── */}
      {open && (
        <div
          className="fixed inset-0 z-40"
          style={{ backgroundColor: 'rgba(0,0,0,0.4)' }}
          onClick={() => setOpen(false)}
        />
      )}

      {/* ─── Side Drawer ─── */}
      <div
        className="fixed top-0 left-0 z-50 flex flex-col"
        style={{
          width: '260px',
          height: '100dvh',
          backgroundColor: '#ffffff',
          transform: open ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 0.25s ease',
          boxShadow: open ? '4px 0 24px rgba(0,0,0,0.15)' : 'none',
        }}
      >
        {/* 抽屜頂部 */}
        <div
          className="flex items-center justify-between px-5"
          style={{ height: '52px', backgroundColor: '#729DAD', flexShrink: 0 }}
        >
          <span className="text-base font-bold" style={{ color: '#ffffff' }}>後台管理</span>
          <button
            onClick={() => setOpen(false)}
            className="flex items-center justify-center rounded-lg"
            style={{ width: 32, height: 32, color: '#ffffff' }}
            aria-label="關閉選單"
          >
            <X size={20} />
          </button>
        </div>

        {/* 導覽項目 */}
        <nav className="flex flex-col py-3" style={{ flex: 1 }}>
          {NAV_ITEMS.map(({ href, label, Icon }) => {
            const isActive = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setOpen(false)}
                className="flex items-center gap-3 px-5 py-3.5 text-sm font-semibold transition-colors"
                style={{
                  backgroundColor: isActive ? '#edf5f7' : 'transparent',
                  color: isActive ? '#5a8494' : '#4a5568',
                  borderLeft: isActive ? '3px solid #729DAD' : '3px solid transparent',
                }}
              >
                <Icon size={18} color={isActive ? '#729DAD' : '#8a9a9f'} />
                {label}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* ─── Page Content ─── */}
      {children}
    </>
  );
}
