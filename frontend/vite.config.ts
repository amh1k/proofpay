import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // 127.0.0.1, NOT localhost. On some Windows setups `localhost` resolves to
      // IPv6 ::1 while uvicorn binds IPv4, and you get a connection-refused that
      // looks exactly like a bug in your own code. This costs people an hour.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
