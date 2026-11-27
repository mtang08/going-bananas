import { defineConfig, type Plugin } from 'vite'
import { servedByGo } from './goRoutes'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'

const guidePath = fileURLToPath(new URL('../docs/user-guide.md', import.meta.url))

function loopbackTarget(port: string): string {
  if (!/^[1-9]\d{0,4}$/.test(port) || Number(port) > 65535)
    throw new Error('Proxy port must be an integer from 1 to 65535')
  return `http://127.0.0.1:${port}`
}

const goProxy: Plugin = {
  name: 'going-bananas-go-dev-proxy',
  configureServer(server) {
    const port = process.env.PROPOSAL_GO_PORT
    if (port === undefined) return
    if (process.env.APP_MODE !== 'test' && process.env.APP_MODE !== 'demo')
      throw new Error('PROPOSAL_GO_PORT requires APP_MODE=test or demo')
    const target = loopbackTarget(port)
    server.config.server.proxy = {
      '/api': {
        target: loopbackTarget(process.env.APP_PORT ?? '8000'),
        changeOrigin: true,
        configure(proxy) {
          server.middlewares.use((req, res, next) => {
            const path = req.url?.split('?', 1)[0] ?? ''
            if (servedByGo(req.method, path)) return proxy.web(req, res, { target })
            next()
          })
        },
      },
    }
  },
}

export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  plugins: [
    goProxy,
    react(),
    tailwindcss(),
    {
      name: 'going-bananas-user-guide',
      resolveId(id) {
        if (id === 'virtual:user-guide') return '\0virtual:user-guide'
      },
      load(id) {
        if (id !== '\0virtual:user-guide') return
        // Bundle this one public document without serving the repository's files.
        this.addWatchFile(guidePath)
        return `export default ${JSON.stringify(readFileSync(guidePath, 'utf8'))}`
      },
    },
  ],
  server: { host: '127.0.0.1', proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'] },
})
