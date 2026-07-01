import { create } from "zustand";
import { persist } from "zustand/middleware";

// CR-038 §A3 — persisted shell preferences. The contextual left rail can be
// collapsed; the choice survives reloads (mirrors the useProjectStore pattern).
interface LayoutPrefsState {
  railCollapsed: boolean;
  setRailCollapsed: (v: boolean) => void;
  toggleRail: () => void;
}

export const useLayoutPrefs = create<LayoutPrefsState>()(
  persist(
    (set) => ({
      railCollapsed: false,
      setRailCollapsed: (railCollapsed) => set({ railCollapsed }),
      toggleRail: () => set((s) => ({ railCollapsed: !s.railCollapsed })),
    }),
    { name: "yapi-layout-prefs" }
  )
);
