import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  BarChart3,
  BookOpen,
  CalendarClock,
  CalendarDays,
  CookingPot,
  ChefHat,
  Download,
  HelpCircle,
  History,
  Home,
  Leaf,
  MoreHorizontal,
  ScanBarcode,
  Settings,
  ShieldCheck,
  ShoppingBasket,
  Package,
} from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'
import { useAiStatus, useDashboard } from '../api/queries'
import { useSyncStatus } from '../offline'
import { cn } from '../lib/format'
import { SyncPill } from './SyncPill'
import { Modal, Spinner } from './ui'
import { ErrorBoundary } from './ErrorBoundary'

interface NavDef {
  to: string
  label: string
  icon: ReactNode
  end?: boolean
  badge?: number
}

export default function AppShell() {
  const { t } = useTranslation()
  const { me, isAdmin } = useAuth()
  const ai = useAiStatus()
  const dash = useDashboard()
  const qc = useQueryClient()
  const sync = useSyncStatus()
  const loc = useLocation()
  const [more, setMore] = useState(false)

  // Refresh server state after a background sync completes.
  useEffect(() => {
    if (sync.lastSyncAt) {
      for (const k of ['inventory', 'inventory-detail', 'dashboard', 'shopping']) void qc.invalidateQueries({ queryKey: [k] })
    }
  }, [sync.lastSyncAt, qc])

  const unknown = dash.data?.unknown_count ?? 0
  const primary: NavDef[] = [
    { to: '/', label: t('nav.home'), icon: <Home />, end: true },
    { to: '/inventory', label: t('nav.inventory'), icon: <Package /> },
    { to: '/shopping', label: t('nav.shopping'), icon: <ShoppingBasket />, badge: dash.data?.shopping_open_count },
  ]
  const secondary: NavDef[] = [
    { to: '/recipes', label: t('nav.recipes'), icon: <BookOpen /> },
    { to: '/plan', label: t('nav.plan'), icon: <CalendarDays /> },
    { to: '/kitchen', label: t('nav.kitchen'), icon: <CookingPot /> },
    { to: '/expiring', label: t('nav.expiring'), icon: <CalendarClock /> },
    { to: '/unknown', label: t('nav.unknown'), icon: <HelpCircle />, badge: unknown },
    { to: '/stats', label: t('nav.stats'), icon: <BarChart3 /> },
    { to: '/activity', label: t('nav.activity'), icon: <History /> },
    ...(ai.data?.enabled ? [{ to: '/assistant', label: t('nav.assistant'), icon: <ChefHat /> }] : []),
    { to: '/export', label: t('nav.export'), icon: <Download /> },
    { to: '/settings', label: t('nav.settings'), icon: <Settings /> },
    ...(isAdmin ? [{ to: '/admin', label: t('nav.admin'), icon: <ShieldCheck /> }] : []),
  ]

  const linkCls = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex min-h-11 items-center gap-3 rounded-xl px-3.5 text-[15px] font-medium transition-colors [&_svg]:size-5',
      isActive ? 'bg-leaf-100 font-semibold text-leaf-700' : 'text-ink-700 hover:bg-cream-200/70 hover:text-ink-900',
    )

  return (
    <div className="min-h-dvh lg:pl-64">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[70] focus:rounded-lg focus:bg-surface focus:p-3">
        {t('nav.skip')}
      </a>
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col gap-1 border-r border-cream-200/70 bg-cream-50 p-4 lg:flex">
        <div className="mb-4 flex items-center gap-2 px-2 pt-2">
          <div className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-leaf-500 to-leaf-800 text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.2),0_10px_24px_-12px_var(--color-leaf-600)]">
            <Leaf className="size-5" />
          </div>
          <div>
            <div className="text-[17px] font-bold leading-none tracking-[-0.02em]">PantryNanny</div>
            <div className="text-xs text-ink-500">{me?.household.name}</div>
          </div>
        </div>
        <NavLink to="/scan" className="mb-3 flex min-h-12 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-leaf-500 to-leaf-800 font-semibold text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.2),0_10px_24px_-12px_var(--color-leaf-600)] transition-transform hover:brightness-110 active:scale-[0.98]">
          <ScanBarcode className="size-5" /> {t('nav.scan')}
        </NavLink>
        <nav aria-label={t('nav.main')} className="flex flex-col gap-1">
          {[...primary, ...secondary].map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={linkCls}>
              {n.icon}
              <span className="flex-1">{n.label}</span>
              {!!n.badge && <span className="rounded-full bg-tomato-500 px-2 text-xs text-white">{n.badge}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-1">
          <SyncPill />
        </div>
      </aside>

      {/* Top bar (phones) */}
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-cream-200/60 bg-cream-100/75 px-4 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] backdrop-blur-xl lg:hidden">
        <span className="flex items-center gap-2 text-[17px] font-bold tracking-[-0.02em]">
          <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-leaf-500 to-leaf-800 text-white">
            <Leaf className="size-4" />
          </span>
          PantryNanny
        </span>
        <SyncPill />
      </header>
      <div className="hidden justify-end px-8 pt-4 lg:flex" />

      <main id="main" className="mx-auto w-full max-w-5xl px-4 pb-28 pt-2 lg:px-8 lg:pb-12 lg:pt-6">
        <ErrorBoundary key={loc.pathname}>
          <Suspense fallback={<Spinner />}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </main>

      {/* Bottom tab bar (phones/tablets) */}
      <nav
        aria-label={t('nav.main')}
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-cream-200/70 bg-surface/80 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
      >
        {primary.slice(0, 2).map((n) => (
          <Tab key={n.to} n={n} />
        ))}
        <NavLink to="/scan" aria-label={t('nav.scan')} className="relative grid place-items-center">
          <span className="-mt-6 grid size-16 place-items-center rounded-full bg-gradient-to-br from-leaf-500 to-leaf-800 text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.2),0_10px_24px_-12px_var(--color-leaf-600)] ring-4 ring-cream-100 transition-transform active:scale-95">
            <ScanBarcode className="size-7" />
          </span>
        </NavLink>
        <Tab n={primary[2]} />
        <button
          onClick={() => setMore(true)}
          className="relative flex min-h-16 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold text-ink-500 [&_svg]:size-6"
        >
          <MoreHorizontal />
          {t('nav.more')}
          {unknown > 0 && <span className="absolute right-4 top-2 size-2.5 rounded-full bg-tomato-500" />}
        </button>
      </nav>

      <Modal open={more} onClose={() => setMore(false)} title={t('nav.more')}>
        <div className="grid grid-cols-2 gap-2 pb-2">
          {secondary.map((n) => (
            <NavLink key={n.to} to={n.to} onClick={() => setMore(false)} className={({ isActive }) => cn(linkCls({ isActive }), 'bg-cream-100')}>
              {n.icon}
              <span className="flex-1">{n.label}</span>
              {!!n.badge && <span className="rounded-full bg-tomato-500 px-2 text-xs text-white">{n.badge}</span>}
            </NavLink>
          ))}
        </div>
      </Modal>
    </div>
  )
}

function Tab({ n }: { n: NavDef }) {
  return (
    <NavLink
      to={n.to}
      end={n.end}
      className={({ isActive }) =>
        cn(
          'relative flex min-h-16 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold [&_svg]:size-6',
          isActive ? 'text-leaf-700' : 'text-ink-500',
        )
      }
    >
      {n.icon}
      {n.label}
      {!!n.badge && (
        <span className="absolute right-[22%] top-1.5 rounded-full bg-tomato-500 px-1.5 text-[10px] text-white">{n.badge}</span>
      )}
    </NavLink>
  )
}
