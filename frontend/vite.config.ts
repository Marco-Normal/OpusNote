import { defineConfig, type Plugin } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

/**
 * Read an override from the environment without depending on @types/node in a
 * browser-targeted tsconfig.
 */
const nodeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
const apiTarget = nodeEnv?.SRT_API_TARGET ?? 'http://127.0.0.1:8000';

/**
 * Carry the third-party attribution into the built bundle.
 *
 * MIT and BSD-3-Clause both require the copyright and permission notices to travel with
 * redistributed copies, and `dist` *is* redistributed — the API serves it. Minification strips
 * the licence comments the dependencies ship with, so without this the built client would carry
 * other people's code and none of their notices.
 *
 * This is a plugin rather than `build.rolldownOptions.output.banner` because Vite 8 omits
 * `banner` from the output options it accepts (`Omit<OutputOptions, …, "banner">`), so setting
 * it there is silently ignored — verified by building and finding no banner in the output.
 * The short form goes in the bundle; the full notices, with copyright lines, are in
 * THIRD-PARTY.md at the repository root.
 */
function licenceBanner(): Plugin {
  const notice =
    '/*! Opus Note — MIT License. Bundles OpenSheetMusicDisplay (BSD-3-Clause), ' +
    'VexFlow (MIT), Tone.js (MIT), JSZip (MIT) and Svelte (MIT). ' +
    'See THIRD-PARTY.md for the full notices. */';

  return {
    name: 'opus-note-licence-banner',
    apply: 'build',
    generateBundle(_options, bundle) {
      for (const item of Object.values(bundle)) {
        if (item.type === 'chunk') item.code = `${notice}\n${item.code}`;
      }
    },
  };
}

export default defineConfig({
  plugins: [svelte(), licenceBanner()],
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
