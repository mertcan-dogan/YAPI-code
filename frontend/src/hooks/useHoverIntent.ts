import { useCallback, useEffect, useRef } from "react";

// CR-038 §A2 — hover-intent timing for the top-bar section menus. A short OPEN
// delay stops a dropdown flickering open when the pointer merely crosses a
// trigger; a slightly longer CLOSE delay lets the pointer travel from the
// trigger into the panel without the menu snapping shut. Click and keyboard
// callers bypass the delay (they call the open/close setter directly).
export function useHoverIntent(openDelay = 120, closeDelay = 180) {
  const timer = useRef<number | null>(null);

  const cancel = useCallback(() => {
    if (timer.current != null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const schedule = useCallback(
    (fn: () => void, delay: number) => {
      cancel();
      timer.current = window.setTimeout(() => {
        timer.current = null;
        fn();
      }, delay);
    },
    [cancel]
  );

  const scheduleOpen = useCallback((fn: () => void) => schedule(fn, openDelay), [schedule, openDelay]);
  const scheduleClose = useCallback((fn: () => void) => schedule(fn, closeDelay), [schedule, closeDelay]);

  useEffect(() => cancel, [cancel]);

  return { scheduleOpen, scheduleClose, cancel };
}
