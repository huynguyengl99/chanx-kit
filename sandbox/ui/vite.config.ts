import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ws': { target: 'ws://localhost:8000', ws: true },
      '/asyncapi': 'http://localhost:8000',
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
});
