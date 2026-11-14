import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev only: mirror the Caddy route so the frontend calls /api the same way as in prod.
const BACKEND_URL = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': BACKEND_URL,
    },
  },
})
