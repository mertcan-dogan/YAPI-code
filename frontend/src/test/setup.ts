import "@testing-library/jest-dom";

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
