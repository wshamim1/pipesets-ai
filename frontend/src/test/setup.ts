import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Vitest runs without globals, so Testing Library can't register its own cleanup
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
