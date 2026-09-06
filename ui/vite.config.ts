import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Binds 0.0.0.0 by default (overridable) so the Floor scene is reachable
// over Tailscale from a phone during dev, not just localhost.
export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.VITE_DEV_HOST ?? '0.0.0.0',
    port: process.env.VITE_DEV_PORT ? Number(process.env.VITE_DEV_PORT) : 5173,
  },
})
