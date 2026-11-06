import react from '@vitejs/plugin-react'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { searchForWorkspaceRoot, type Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

const BACKEND = process.env.VITE_DEV_BACKEND || 'http://localhost:8000'

// The user guide (docs/guide/) and the architecture pages (docs/architecture/) live in the repo's
// docs/ folder and are bundled into Docs (src/utils/guides.ts). Docker builds get that folder as the
// extra build context "docs" (Dockerfile).
const DOC_DIRS = ['../docs/guide', '../docs/architecture'].map((dir) => fileURLToPath(new URL(dir, import.meta.url)))

// Public chat links (/c/<token>) open chat.html, its own small bundle, not the builder's index.html.
// nginx does the same in production (nginx.conf.template, deploy/edge).
const chatLinkPages = (): Plugin => ({
  name: 'chat-link-pages',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.url && /^\/c\/[^/?#]+\/?(\?|$)/.test(req.url)) req.url = '/chat.html'
      next()
    })
  },
})

// Settings → About shows what the UI was built with: the installed versions (not package.json ranges)
const installed = (pkg: string): string => {
  try {
    return (createRequire(import.meta.url)(`${pkg}/package.json`) as { version: string }).version
  } catch {
    return ''
  }
}
const FRONTEND_BUILD = {
  builtAt: new Date().toISOString(),
  libraries: [
    ['React', 'react', 'UI framework'], ['React Flow', '@xyflow/react', 'Pipeline canvas'],
    ['Lucide', 'lucide-react', 'Icons'], ['Vite', 'vite', 'Build tool and dev server'],
    ['TypeScript', 'typescript', 'Language'], ['Mermaid', 'mermaid', 'Diagrams in Docs'],
  ].map(([name, pkg, role]) => ({ name, version: installed(pkg), role })).filter((l) => l.version),
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), chatLinkPages()],
  define: { __FRONTEND_BUILD__: JSON.stringify(FRONTEND_BUILD) },
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('index.html', import.meta.url)),
        chat: fileURLToPath(new URL('chat.html', import.meta.url)),
      },
    },
  },
  server: {
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), ...DOC_DIRS] },
    // Dev only: let an ngrok tunnel reach the dev server (e.g. to try the UI on a phone).
    // Opened through it, the UI calls the API on its own origin (src/types.ts), proxied here.
    allowedHosts: ['.ngrok-free.app', '.ngrok.app', '.ngrok.io'],
    proxy: {
      '/api': BACKEND,
      '/v1': BACKEND,
      '/health': BACKEND,
    },
  },
  test: {
    // Hooks and config panels render into a DOM; the pure utils tests don't mind it
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
  },
})
