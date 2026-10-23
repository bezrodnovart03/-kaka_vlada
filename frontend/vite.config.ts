import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Фронт и API на одном origin (docs/API.md §1): в dev /api проксируется на Django.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  preview: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
});
