/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Load env vars from repo root so frontend can consume VITE_* from main .env.
  envDir: resolve(__dirname, '..'),
  base: '/static/',
  build: {
    outDir: resolve(__dirname, '../backend/app/static'),
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, './src')
    }
  }
})


