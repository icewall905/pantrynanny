import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AuthProvider, RequireAdmin, RequireAuth } from './auth/AuthProvider'
import { ToastProvider } from './components/Toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Spinner } from './components/ui'
import AppShell from './components/AppShell'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import InventoryPage from './pages/InventoryPage'
import NotFoundPage from './pages/NotFoundPage'

// /scan is owned by the scanner ticket: full-screen, no app chrome, lazy-loaded.
// It is intentionally NOT behind RequireAuth: an unpaired kiosk iPad enters its pairing code there.
const ScanPage = lazy(() => import('./pages/ScanPage'))
const ProductDetailPage = lazy(() => import('./pages/ProductDetailPage'))
const NewProductPage = lazy(() => import('./pages/NewProductPage'))
const UnknownPage = lazy(() => import('./pages/UnknownPage'))
const ShoppingPage = lazy(() => import('./pages/ShoppingPage'))
const ExpiringPage = lazy(() => import('./pages/ExpiringPage'))
const StatsPage = lazy(() => import('./pages/StatsPage'))
const ExportPage = lazy(() => import('./pages/ExportPage'))
const AssistantPage = lazy(() => import('./pages/AssistantPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))
const KitchenPage = lazy(() => import('./pages/KitchenPage'))

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/scan"
              element={
                <div className="pn-scan-palette">
                  <Suspense fallback={<Spinner />}>
                    <ScanPage />
                  </Suspense>
                </div>
              }
            />
            <Route
              path="/kitchen"
              element={
                <RequireAuth>
                  <Suspense fallback={<Spinner />}>
                    <KitchenPage />
                  </Suspense>
                </RequireAuth>
              }
            />
            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route index element={<DashboardPage />} />
              <Route path="inventory" element={<InventoryPage />} />
              <Route path="products/new" element={<NewProductPage />} />
              <Route path="products/:id" element={<ProductDetailPage />} />
              <Route path="unknown" element={<UnknownPage />} />
              <Route path="shopping" element={<ShoppingPage />} />
              <Route path="expiring" element={<ExpiringPage />} />
              <Route path="stats" element={<StatsPage />} />
              <Route path="export" element={<ExportPage />} />
              <Route path="assistant" element={<AssistantPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route
                path="admin"
                element={
                  <RequireAdmin>
                    <AdminPage />
                  </RequireAdmin>
                }
              />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </ErrorBoundary>
  )
}
