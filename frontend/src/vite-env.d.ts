/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SHOW_DEBUG_VALUES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
