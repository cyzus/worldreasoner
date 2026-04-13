import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'
import { readFileSync } from 'fs'
import { resolve } from 'path'

function loadDotEnv() {
  try {
    const raw = readFileSync(resolve(__dirname, '../.env'), 'utf-8')
    return Object.fromEntries(
      raw.split('\n')
        .filter(line => line.includes('=') && !line.startsWith('#'))
        .map(line => line.split('=').map(s => s.trim()))
    )
  } catch {
    return {}
  }
}

const env = loadDotEnv()
const FRONTEND_PORT = parseInt(env.FRONTEND_PORT ?? '5173')
const FRONTEND_HOST = env.FRONTEND_HOST ?? '127.0.0.1'
const BACKEND_PORT = parseInt(env.BACKEND_PORT ?? '8018')
const BACKEND_HOST = env.BACKEND_HOST ?? '127.0.0.1'

export default defineConfig({
  plugins: [
    react(),
    visualizer({
      filename: './dist/stats.html',
      open: false, // Set to true to auto-open bundle analysis
      gzipSize: true,
      brotliSize: true,
    }),
  ],

  build: {
    target: 'es2020',
    sourcemap: true,

    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'd3': ['d3'],
          'graph': ['react-force-graph-2d'],
          'http': ['axios'],
          'query': ['@tanstack/react-query'],
          'state': ['zustand'],
        },
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
      },
    },

    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
      },
    },

    chunkSizeWarningLimit: 500,
  },

  optimizeDeps: {
    include: ['react', 'react-dom'],
  },

  server: {
    host: FRONTEND_HOST,
    port: FRONTEND_PORT,
    strictPort: true,
    proxy: {
      '/api': {
        target: `http://${BACKEND_HOST}:${BACKEND_PORT}`,
        changeOrigin: true,
        ws: true,
      },
      '/ws': {
        target: `ws://${BACKEND_HOST}:${BACKEND_PORT}`,
        ws: true,
      },
    },
  },
})
