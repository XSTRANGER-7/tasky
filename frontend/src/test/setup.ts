import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'
import { MotionGlobalConfig } from 'framer-motion'

// Animations finish instantly in tests (jsdom has no frames to run them on).
MotionGlobalConfig.skipAnimations = true

// jsdom lacks a few browser APIs the UI relies on (Recharts, cmdk, infinite scroll).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
globalThis.IntersectionObserver ??=
  IntersectionObserverStub as unknown as typeof IntersectionObserver
Element.prototype.scrollIntoView ??= function scrollIntoView() {}
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => undefined,
  removeListener: () => undefined,
  addEventListener: () => undefined,
  removeEventListener: () => undefined,
  dispatchEvent: () => false,
})) as typeof window.matchMedia

// jsdom's AbortSignal is not the one Node's native Request accepts ("Expected signal
// to be an instance of AbortSignal"). Browsers are fine; in tests, drop the foreign
// signal so queries that pass one for cancellation can still build requests.
const NativeRequest = globalThis.Request
globalThis.Request = class extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    const rest = { ...init }
    delete rest.signal
    super(input, rest)
  }
}

// Route chunks are lazy-loaded and transformed on first use; give `findBy*` room for that.
configure({ asyncUtilTimeout: 3000 })
