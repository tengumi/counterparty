import { defineConfig } from 'vite';

// Сборка входит в Python-пакет: обычный запуск не требует отдельного Node-сервера.
export default defineConfig({
  base: '/ui/',
  build: { outDir: '../src/counterparty_agent/ui/build', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
