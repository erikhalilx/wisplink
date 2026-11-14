import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  publicDir: fileURLToPath(new URL('../wisplink/brand', import.meta.url)),
  server: {
    host: 'localhost',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api/v1': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/oauth': { target: 'http://127.0.0.1:8001', changeOrigin: false },
    },
  },
})
