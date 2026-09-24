/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the SPA and API are same-origin through this proxy, exactly as they
// are in production through the Vercel /api/* rewrite (see vercel.json).
const apiTarget = process.env.VITE_DEV_API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: apiTarget, changeOrigin: true } },
    // Playwright writes reports here during a run; they must not trigger page reloads.
    watch: { ignored: ['**/playwright-report/**', '**/test-results/**', '**/e2e/**'] },
  },
  build: {
    sourcemap: true,
    target: 'es2022',
    rollupOptions: {
      output: {
        // Stable vendor code in its own long-cached chunks; app code changes often.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          data: ['@tanstack/react-query', 'openapi-fetch'],
          ui: [
            'framer-motion',
            'cmdk',
            'sonner',
            '@radix-ui/react-dialog',
            '@radix-ui/react-dropdown-menu',
            '@radix-ui/react-popover',
          ],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
})
