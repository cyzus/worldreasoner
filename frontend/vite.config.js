import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'

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
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8018',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8018',
        ws: true,
      },
    },
  },
})
