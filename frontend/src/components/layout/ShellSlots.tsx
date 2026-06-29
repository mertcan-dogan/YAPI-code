import * as React from "react";

// CR-038 §7-C — durable 3-zone layout primitive. The shell (AppLayout) owns a
// left-rail slot and a right-panel slot; a page that owns stateful rail content
// (the Yapı AI page: conversations + live stream) hands a rendered node into the
// slot via `useLeftRail` / `useRightPanel`. Future CRs (CR-039 conversational
// preview, the "Çalışma Alanı" panel) drop into these slots WITHOUT re-touching
// AppLayout.
//
// Store-backed rails (the active-project submenu, the studio sub-rail) are NOT
// routed through here — AppLayout renders them directly from the route, because
// they read their own store and must survive independent of any page. Rule for
// later CRs: slot for page-state rails; direct render for store-backed rails.
interface ShellSlotsValue {
  leftRail: React.ReactNode | null;
  rightPanel: React.ReactNode | null;
  setLeftRail: (node: React.ReactNode | null) => void;
  setRightPanel: (node: React.ReactNode | null) => void;
}

const noop = () => {};

// Default value is inert so a page can call the hooks WITHOUT a provider present
// (e.g. AIAssistantPage rendered alone in a unit test) — the setters no-op and
// nothing renders into a slot.
const ShellSlotsContext = React.createContext<ShellSlotsValue>({
  leftRail: null,
  rightPanel: null,
  setLeftRail: noop,
  setRightPanel: noop,
});

export function ShellSlotsProvider({ children }: { children: React.ReactNode }) {
  const [leftRail, setLeftRail] = React.useState<React.ReactNode | null>(null);
  const [rightPanel, setRightPanel] = React.useState<React.ReactNode | null>(null);
  // setLeftRail / setRightPanel from useState are stable across renders, so the
  // memoised value only changes when slot content actually changes.
  const value = React.useMemo<ShellSlotsValue>(
    () => ({ leftRail, rightPanel, setLeftRail, setRightPanel }),
    [leftRail, rightPanel]
  );
  return <ShellSlotsContext.Provider value={value}>{children}</ShellSlotsContext.Provider>;
}

export function useShellSlots(): ShellSlotsValue {
  return React.useContext(ShellSlotsContext);
}

// Register left-rail content. Pass a MEMOISED node (keyed by the real state it
// depends on) so the slot only updates when that data changes — not on every
// render (e.g. not on each streamed token). Cleared automatically on unmount.
export function useLeftRail(node: React.ReactNode | null): void {
  const { setLeftRail } = useShellSlots();
  React.useEffect(() => {
    setLeftRail(node);
    return () => setLeftRail(null);
  }, [node, setLeftRail]);
}

// Register right-panel content (same contract as useLeftRail).
export function useRightPanel(node: React.ReactNode | null): void {
  const { setRightPanel } = useShellSlots();
  React.useEffect(() => {
    setRightPanel(node);
    return () => setRightPanel(null);
  }, [node, setRightPanel]);
}
