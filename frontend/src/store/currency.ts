import { create } from "zustand";
import { persist } from "zustand/middleware";

// CR-014-D: per-user display preference for the ₺ / $ / İkisi de toggle.
// Default "both" (TRY primary, USD alongside). Persisted to localStorage.
export type CurrencyMode = "try" | "usd" | "both";

interface CurrencyState {
  mode: CurrencyMode;
  setMode: (m: CurrencyMode) => void;
}

export const useCurrency = create<CurrencyState>()(
  persist(
    (set) => ({
      mode: "both",
      setMode: (mode) => set({ mode }),
    }),
    { name: "yapi-currency-mode" }
  )
);
