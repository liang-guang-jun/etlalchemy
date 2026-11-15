import { fileURLToPath } from 'node:url';
import type { IncomingMessage } from 'node:http';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const BACKEND = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000';

/**
 * Path prefixes served by the FastAPI application. During development the Vite
 * server proxies them, so the browser sees one origin and no CORS preflight is
 * needed. In production the SPA is served from the same origin as the API.
 */
const PROXIED_PREFIXES = [
  '/agent',
  '/catalog',
  '/semantic',
  '/vocabulary',
  '/ingestion',
  '/comments',
  '/iam',
  '/mcp',
];

/**
 * Keeps client-side routes such as `/iam/users` working on reload.
 *
 * The SPA routes start with the same prefixes as the API, so a browser
 * navigation (which asks for HTML) must be answered with `index.html` while an
 * XHR keeps going to the backend.
 *
 * @param request Incoming proxy request.
 * @returns `'/index.html'` for a document request, otherwise `undefined`.
 */
function bypassDocumentRequest(request: IncomingMessage): string | undefined {
  const accept = request.headers.accept ?? '';
  return accept.includes('text/html') ? '/index.html' : undefined;
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // The production bundle lives in the project root next to the Python code,
    // not inside `frontend/`, so it can be published as a single artifact.
    // `emptyOutDir` is required because the directory sits outside Vite's root.
    outDir: fileURLToPath(new URL('../dist/ui', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      PROXIED_PREFIXES.map((prefix) => [
        prefix,
        { target: BACKEND, changeOrigin: true, bypass: bypassDocumentRequest },
      ]),
    ),
  },
});
