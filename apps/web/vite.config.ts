import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    // The Agent Service RPC is same-origin in production; proxy it during dev.
    proxy: {
      '/api/v1': { target: 'http://localhost:8000', changeOrigin: true },
      '/rpc/agent': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
});
