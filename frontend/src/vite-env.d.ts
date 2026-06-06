/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Vite client type declarations for the Syx frontend.
 *
 * Declares the typed shape of environment variables exposed on
 * `import.meta.env` to the application.
 */
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SHOW_DEBUG_VALUES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
