import { create } from "zustand";
import { supabase } from "@/lib/supabase";
import { apiGet, apiPost } from "@/lib/api";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  init: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, companyName: string, fullName: string) => Promise<void>;
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

  register: async (email, password, companyName, fullName) => {
    // 1) Create the Supabase Auth user.
    const { data, error } = await supabase.auth.signUp({ email, password });
    if (error) throw new Error(error.message || "Kayıt başarısız");
    // 2) If a session was returned (email confirmation off), provision the
    //    company + director row immediately. Otherwise the user must confirm
    //    their email, then sign in (login() → register fallback in App).
    if (!data.session) {
      throw new Error("Hesabınız oluşturuldu. Lütfen e-postanızı onaylayıp giriş yapın.");
    }
    await apiPost("/auth/register", { company_name: companyName, full_name: fullName, email });
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
