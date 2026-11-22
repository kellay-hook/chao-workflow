import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(() => {
  const target = process.env.VITE_API_TARGET || 'http://127.0.0.1:8020'
  return {
    plugins: [react()],
    server: {
      port: 5180,
      proxy: {
        '/api': target,
        '/healthz': target,
      },
    },
  }
})
