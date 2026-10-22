import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      input: 'index.html',
      external: ['@replit/extensions', '@replit/extensions-react'],
      output: {
        globals: {
          '@replit/extensions': 'replitExtensions',
          '@replit/extensions-react': 'replitExtensionsReact',
        },
      },
    },
  },
  server: {
    port: 5173,
    host: true,
    allowedHosts: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './tests/setup.ts',
    include: ['tests/**/*.{test,spec}.{ts,tsx}'],
  },
});