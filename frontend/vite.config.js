import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'
import { readFileSync } from 'fs'
import { resolve } from 'path'

function loadDotEnv() {
  try {
    const raw = readFileSync(resolve(__dirname, '../.env'), 'utf-8')
    return Object.fromEntries(
      raw.split('\n')
        .filter(line => line.includes('=') && !line.trim().startsWith('#'))
        .map(line => {
          const index = line.indexOf('=')
          const key = line.slice(0, index).trim()
          const value = line.slice(index + 1).trim()
          return [key, value]
        })
    )
  } catch {
    return {}
  }
}

function parseInteger(value) {
  if (!value) {
    return null
  }

  const parsed = Number.parseInt(value, 10)
  return Number.isNaN(parsed) ? null : parsed
}

function extractServerPortFromYaml(yamlText) {
  const lines = yamlText.split(/\r?\n/)
  let inServerBlock = false
  let serverIndent = -1

  for (const line of lines) {
    const uncommented = line.replace(/\s+#.*$/, '')
    const trimmed = uncommented.trim()

    if (!trimmed) {
      continue
    }

    const indent = line.match(/^\s*/)[0].length

    if (!inServerBlock && /^server:\s*$/.test(trimmed)) {
      inServerBlock = true
      serverIndent = indent
      continue
    }

    if (!inServerBlock) {
      continue
    }

    if (indent <= serverIndent && /^[A-Za-z0-9_-]+:\s*/.test(trimmed)) {
      break
    }

    const portMatch = trimmed.match(/^port:\s*(\d+)\s*$/)
    if (portMatch) {
      return Number.parseInt(portMatch[1], 10)
    }
  }

  return null
}

function loadBackendPortFromConfig() {
  const candidateFiles = [
    resolve(__dirname, '../config/config.yaml'),
    resolve(__dirname, '../config/config.example.yaml'),
  ]

  for (const filePath of candidateFiles) {
    try {
      const raw = readFileSync(filePath, 'utf-8')
      const parsedPort = extractServerPortFromYaml(raw)
      if (parsedPort !== null) {
        return parsedPort
      }
    } catch {
      // Ignore missing/unreadable files and continue fallback chain.
    }
  }

  return null
}

const env = loadDotEnv()
const FRONTEND_PORT = parseInteger(env.FRONTEND_PORT) ?? 5173
const FRONTEND_HOST = env.FRONTEND_HOST ?? '127.0.0.1'
const BACKEND_PORT = parseInteger(env.BACKEND_PORT)
  ?? parseInteger(env.WORLDREASONER__SERVER__PORT)
  ?? loadBackendPortFromConfig()
  ?? 8300
const BACKEND_HOST = env.BACKEND_HOST
  ?? env.WORLDREASONER__SERVER__HOST
  ?? '127.0.0.1'

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
