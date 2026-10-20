/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { pwaOptions } from './pwa.config.ts'
import { VitePWA } from 'vite-plugin-pwa'

// Backend dev server (uvicorn) – production uses nginx on :8734 for the same paths.
const API = process.env.PN_API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss(), VitePWA(pwaOptions)],
  build: {
    // iPadOS Safari 15+ and current Android Chrome
    target: ['es2020', 'safari15'],
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: { '/api': { target: API, changeOrigin: false, ws: true } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // generous timeouts: the CPU-heavy orientation tests and CI/dev machines under load
    testTimeout: 20_000,
  },
})
