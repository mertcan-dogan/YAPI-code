import "@testing-library/jest-dom";
import { afterEach } from "vitest";

// Perf: useFetch + the chrome share an in-memory GET cache (lib/requestCache).
// Clear it between tests so a cached response never leaks into the next test.
// Dynamic import (not a top-level one) so this setup file never pins the real
// lib/api before a test file's vi.mock("@/lib/api") can register.
afterEach(async () => {
  const { clearRequestCache } = await import("@/lib/requestCache");
  clearRequestCache();
});

// jsdom lacks these; react-grid-layout / responsive hooks need them.
class _ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = _ResizeObserver;

// Default matchMedia (mobile); tests override via setMatchMedia().
export function setMatchMedia(matches: boolean) {
  window.matchMedia = ((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
setMatchMedia(false);
