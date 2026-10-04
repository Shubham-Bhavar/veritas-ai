import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the API runs separately; /api is proxied so the app is always same-origin.
const target = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8090'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': { target, changeOrigin: false } },
  },
  preview: {
    proxy: { '/api': { target, changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
  },
})
