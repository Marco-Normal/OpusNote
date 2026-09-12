import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

/**
 * Read an override from the environment without depending on @types/node in a
 * browser-targeted tsconfig.
 */
const nodeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
const apiTarget = nodeEnv?.SRT_API_TARGET ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    strictPort: true,
    // Bound to loopback only, reachable as http://localhost:5173.
    // Web MIDI requires a secure context; localhost qualifies, a LAN IP does not.
    host: 'localhost',
    proxy: {
      // Proxying keeps the browser on a single origin: no CORS preflight, and
      // no mixed-content surprise when the API later sits behind HTTPS.
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
