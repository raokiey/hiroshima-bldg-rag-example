import { defineConfig } from 'vite'

export default defineConfig({
  // 本番ビルド: FastAPI が /static 配下にマウントするため、
  // アセット参照も /static/assets/... になるよう base を合わせる
  base: '/static/',
  // 開発時: /api/* を FastAPI (port 8000) にプロキシ
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  // 本番ビルド: src/static/ に出力 → FastAPI が配信
  build: {
    outDir: '../src/static',
    emptyOutDir: true,
  },
})
