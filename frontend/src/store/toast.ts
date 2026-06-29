import { create } from "zustand";

export type ToastKind = "success" | "error" | "warning" | "info";

// CR-044.1 — an optional inline action button (e.g. "İndir" on the skill-run
// toast). When present the toast lingers longer so the user can click it.
export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  action?: ToastAction;
}

interface ToastOpts {
  action?: ToastAction;
}

interface ToastState {
  toasts: Toast[];
  push: (kind: ToastKind, message: string, action?: ToastAction) => void;
  dismiss: (id: number) => void;
}

let counter = 0;

export const useToast = create<ToastState>((set) => ({
  toasts: [],
  push: (kind, message, action) => {
    const id = ++counter;
    set((s) => ({ toasts: [...s.toasts, { id, kind, message, action }] }));
    // An actionable toast lingers (8s) so the user can click it; otherwise
    // success 3s, errors 5s (Section 10.3).
    const ttl = action ? 8000 : kind === "error" ? 5000 : 3000;
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), ttl);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

// Convenience helpers. Pass `{ action: { label, onClick } }` to attach a button.
export const toast = {
  success: (m: string, opts?: ToastOpts) => useToast.getState().push("success", m, opts?.action),
  error: (m: string, opts?: ToastOpts) => useToast.getState().push("error", m, opts?.action),
  warning: (m: string, opts?: ToastOpts) => useToast.getState().push("warning", m, opts?.action),
  info: (m: string, opts?: ToastOpts) => useToast.getState().push("info", m, opts?.action),
};
