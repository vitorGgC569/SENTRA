import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/desktop-assets/',
  build: {
    outDir: '../static/desktop-assets',
    emptyOutDir: false,
    assetsDir: '',
    sourcemap: false,
    rolldownOptions: {
      output: {
        entryFileNames: 'desktop.js',
        chunkFileNames: 'chunk-[hash].js',
        assetFileNames: 'desktop.[ext]',
      },
    },
  },
});
