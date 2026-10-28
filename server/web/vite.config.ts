import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Configuration is supplied by the process environment; do not load .env files.
  envDir: false,
});
