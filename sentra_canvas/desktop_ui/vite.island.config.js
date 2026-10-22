import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
export default defineConfig({ base: './', publicDir: false, plugins: [react()], build: {
  outDir: '../../sentra_electron/island', emptyOutDir: true,
  rolldownOptions: { input: fileURLToPath(new URL('./island.html', import.meta.url)), output: {
    entryFileNames: 'island.js', chunkFileNames: 'chunk-[hash].js', assetFileNames: 'island.[ext]',
  } },
} });
