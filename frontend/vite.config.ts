import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = 'https://127.0.0.1:5000'

// Dev-only shim: main.py's csrf_origin_guard middleware 403s any non-GET request whose
// Origin/Referer isn't https://127.0.0.1:5000 or https://localhost:5000 (deliberate CSRF
// defense on a bot that moves money). The Vite proxy forwards the browser's real Origin
// (Vite's own dev origin) by default, which trips that guard on every POST. This rewrites
// the proxied request's Origin/Referer to the backend's own origin so mutating calls work
// in dev too. Never relax the guard itself in main.py.
function proxyEntry() {
  return {
    target: BACKEND,
    changeOrigin: true,
    secure: false, // backend uses a self-signed cert (cert.pem/key.pem)
    configure: (proxy: any) => {
      proxy.on('proxyReq', (proxyReq: any) => {
        proxyReq.setHeader('Origin', BACKEND)
        proxyReq.setHeader('Referer', `${BACKEND}/`)
      })
    },
  }
}

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    // Build directly into the dir the FastAPI backend serves at https://127.0.0.1:5000/
    // (where Upstox OAuth is configured). emptyOutDir wipes the previous build so there is
    // exactly one UI. `npm run dev` (:5173) is still available for local development.
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': proxyEntry(),
      '/login': proxyEntry(),
      '/callback': proxyEntry(),
      '/ws': { target: BACKEND.replace('https', 'wss'), ws: true, changeOrigin: true, secure: false },
    },
  },
})
