import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// `--mode demo` builds the static GitHub Pages demo (see .env.demo), served from a subpath.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === 'demo' ? './' : '/',
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: {
    chunkSizeWarningLimit: 900, // three.js is most of the bundle
  },
  test: {
    include: ['src/**/*.test.ts'],
  },
}))
