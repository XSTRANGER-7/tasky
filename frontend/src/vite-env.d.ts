/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the REST API. `/api/v1` in every environment (dev proxy / Vercel rewrite). */
  readonly VITE_API_URL?: string
  /** Absolute SSE endpoint on the API domain (Phase 4). */
  readonly VITE_STREAM_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
