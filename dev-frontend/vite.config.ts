import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/** Backend base URL for the Vite `/api` proxy (each daemon uses a unique backend port). */
const proxyTarget = process.env.VITE_DEV_PROXY_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: true,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
