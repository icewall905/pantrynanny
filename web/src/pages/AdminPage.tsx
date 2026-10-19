import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { PageHeader, Spinner, Tabs } from '../components/ui'

const AdminProducts = lazy(() => import('./admin/AdminProducts'))
const AdminCatalogue = lazy(() => import('./admin/AdminCatalogue'))
const AdminTaxonomy = lazy(() => import('./admin/AdminTaxonomy'))
const AdminUsers = lazy(() => import('./admin/AdminUsers'))
const AdminDevices = lazy(() => import('./admin/AdminDevices'))
const AdminProviders = lazy(() => import('./admin/AdminProviders'))
const AdminSettings = lazy(() => import('./admin/AdminSettings'))

const TABS = ['products', 'catalogue', 'taxonomy', 'users', 'devices', 'providers', 'settings'] as const
type Tab = (typeof TABS)[number]

export default function AdminPage() {
  const { t } = useTranslation()
  const [sp, setSp] = useSearchParams()
  const tab = (TABS as readonly string[]).includes(sp.get('tab') ?? '') ? (sp.get('tab') as Tab) : 'products'
  return (
    <>
      <PageHeader title={t('nav.admin')} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`admin.tab_${id}`) }))} value={tab} onChange={(v) => setSp({ tab: v }, { replace: true })} />
      <Suspense fallback={<Spinner />}>
        {tab === 'products' && <AdminProducts />}
        {tab === 'catalogue' && <AdminCatalogue />}
        {tab === 'taxonomy' && <AdminTaxonomy />}
        {tab === 'users' && <AdminUsers />}
        {tab === 'devices' && <AdminDevices />}
        {tab === 'providers' && <AdminProviders />}
        {tab === 'settings' && <AdminSettings />}
      </Suspense>
    </>
  )
}
