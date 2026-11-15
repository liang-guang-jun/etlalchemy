import { fileURLToPath } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const BACKEND = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000';

/**
 * Path prefixes served by the FastAPI application. During development the Vite
 * server proxies them, so the browser sees one origin and no CORS preflight is
 * needed. In production (and inside a Databricks App) FastAPI serves the API
 * and the SPA from the same origin, so the same relative `/api` calls work
 * without any rewrite.
 */
const PROXIED_PREFIXES = ['/api', '/mcp'];

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
      PROXIED_PREFIXES.map((prefix) => [prefix, { target: BACKEND, changeOrigin: true }]),
    ),
  },
});
