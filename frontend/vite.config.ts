import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev only: mirror the Caddy routes so the frontend calls /api and the JWKS the same way as in prod.
const BACKEND_URL = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': BACKEND_URL,
      '/.well-known/jwks.json': BACKEND_URL,
    },
  },
})
