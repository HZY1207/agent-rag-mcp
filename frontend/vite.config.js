import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时：前端跑在 5173，/api 反向代理到后端 8000（SSE 也能正常流式透传）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
