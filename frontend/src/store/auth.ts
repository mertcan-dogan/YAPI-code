import { create } from "zustand";
import { supabase } from "@/lib/supabase";
import { apiGet } from "@/lib/api";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  init: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  fetchProfile: () => Promise<void>;
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  loading: true,

  init: async () => {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (session) {
      await get().fetchProfile();
    }
    set({ loading: false });
    supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) set({ user: null });
    });
  },

  login: async (email, password) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw new Error("E-posta veya şifre hatalı");
    await get().fetchProfile();
  },

  logout: async () => {
    await supabase.auth.signOut();
    set({ user: null });
  },

  fetchProfile: async () => {
    try {
      const { data } = await apiGet<User>("/auth/me");
      set({ user: data });
    } catch {
      set({ user: null });
    }
  },
}));
