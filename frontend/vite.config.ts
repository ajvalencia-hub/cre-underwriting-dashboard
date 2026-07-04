import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // VITE_API_PORT lets the e2e harness point at a scratch backend.
      '/api': `http://127.0.0.1:${process.env.VITE_API_PORT ?? 8000}`,
    },
  },
})
