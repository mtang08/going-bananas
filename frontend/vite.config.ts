import { defineConfig } from 'vite'
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

export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  plugins: [
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
  server: { host: '127.0.0.1', proxy: { '/api': {target: loopbackTarget(process.env.APP_PORT ?? '8000'), changeOrigin: true} } },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'] },
})
