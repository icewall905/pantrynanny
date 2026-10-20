import type { VitePWAOptions } from 'vite-plugin-pwa'

// PWA / service worker configuration. Owned by the scanner/offline ticket.
// Offline *data* lives in IndexedDB (src/offline); the SW only caches the app shell and product images.
export const pwaOptions: Partial<VitePWAOptions> = {
  registerType: 'autoUpdate',
  injectRegister: false, // registered from src/offline (registerServiceWorker)
  // manifest-scan.webmanifest (public/) is the scanner-only manifest swapped in by /scan (src/scan/link.ts)
  includeAssets: ['favicon.svg', 'apple-touch-icon.png', 'manifest-scan.webmanifest'],
  manifest: {
    id: '/',
    name: 'PantryNanny',
    short_name: 'PantryNanny',
    description: 'Husstandens køkkenlager – scan varer ind og ud',
    lang: 'da',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    orientation: 'any',
    background_color: '#fbf8f3',
    theme_color: '#2f7d4f',
    categories: ['food', 'lifestyle', 'productivity'],
    icons: [
      { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
    shortcuts: [
      {
        name: 'Scan varer',
        short_name: 'Scan',
        description: 'Åbn scannerstationen',
        url: '/scan?autostart=1',
        icons: [{ src: '/icon-192.png', sizes: '192x192', type: 'image/png' }],
      },
    ],
  },
  workbox: {
    globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2,webmanifest}'],
    navigateFallback: '/index.html',
    // /downloads/ holds the Android APK: never answer it with the cached app shell.
    navigateFallbackDenylist: [/^\/api\//, /^\/downloads\//],
    cleanupOutdatedCaches: true,
    clientsClaim: true,
    skipWaiting: true,
    maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
    runtimeCaching: [
      {
        // Product images only. Every other /api call is deliberately NOT cached (IndexedDB is the offline source).
        urlPattern: ({ url }) => url.pathname.startsWith('/api/media/'),
        handler: 'CacheFirst',
        options: {
          cacheName: 'pn-product-images',
          expiration: { maxEntries: 400, maxAgeSeconds: 60 * 60 * 24 * 60 },
          cacheableResponse: { statuses: [200] },
        },
      },
    ],
  },
}
