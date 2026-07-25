import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

// In `docker compose up`, frontend and backend run in separate containers, so
// the dev-server proxy's "localhost" would resolve to the frontend container
// itself, not the backend — it needs the Docker network hostname instead.
// docker-compose.yml sets VITE_API_PROXY_TARGET=http://backend:8000 for that
// case. Left unset (the host-run "local dev loop"), it defaults to
// localhost:8000, matching a backend run directly on the host.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/health': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
})
