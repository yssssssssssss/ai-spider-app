import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const FRONTEND_PORT = 6173
const BACKEND_PORT = 8000

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: FRONTEND_PORT,
    strictPort: true,
    proxy: {
      '/api': `http://localhost:${BACKEND_PORT}`
    }
  }
})
