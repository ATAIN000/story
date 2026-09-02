import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3111,
    // P20 宏观流式走 WebSocket；字符串简写不会开 ws，必须显式 ws: true
    proxy: {
      '/api': {
        // 可用 VITE_API_TARGET 覆盖,便于并行开发时指向 worktree 后端
        target: process.env.VITE_API_TARGET || 'http://localhost:8111',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
