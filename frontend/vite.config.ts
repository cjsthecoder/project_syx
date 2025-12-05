/**
 * Copyright (c) 2025 Syx Project Contributors. All rights reserved.
 *
 * This source code is part of the Morpheus project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
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


