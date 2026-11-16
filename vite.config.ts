import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 渲染进程使用相对 base，生产模式下由 Electron 以 file:// 加载
// host 固定为 127.0.0.1，保证 Electron 的 wait-on 与加载地址一致
// watch.ignored 排除非前端目录，避免编辑后端/主进程文件时触发 EBUSY 崩溃
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    watch: {
      ignored: [
        '**/electron/**',
        '**/backend/**',
        '**/packaging/**',
        '**/scripts/**',
        '**/.cache/**',
        '**/outputs/**',
        '**/release/**',
        '**/node_modules/**',
      ],
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
