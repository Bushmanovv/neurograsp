import { defineConfig } from 'vite';

export default defineConfig({
  /* Relative asset URLs, so one build works wherever it is mounted.
     Served from a domain root the emitted ./assets/… resolve to /assets/…;
     served from a project path like /neurograsp/ they resolve under that
     prefix instead. Absolute '/' (the default) only works at a root, and
     silently 404s every script and stylesheet on GitHub Pages. Safe here
     because this is one static page with no client-side routing. */
  base: './',
  server: { host: true, port: 5173 },
  build: { outDir: 'dist', assetsInlineLimit: 0 },
});
