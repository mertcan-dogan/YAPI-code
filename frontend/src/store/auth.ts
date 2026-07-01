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
  acceptInvite: (
    token: string,
    email: string,
    password: string,
    fullName: string,
    mode: "signup" | "signin"
  ) => Promise<void>;
  logout: () => Promise<void>;
  fetchProfile: () => Promise<User | null>;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Right after sign-in the Supabase session can take a beat to be readable by the
// axios interceptor (getSession), so the first /auth/me may 401. Retry briefly
// to absorb that propagation race before giving up.
async function waitForSession(maxMs = 2000): Promise<boolean> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (session?.access_token) return true;
    await sleep(100);
  }
  return false;
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
    // Keep the store in sync with Supabase session changes.
    supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_OUT" || !session) {
        set({ user: null });
      }
    });
  },

  login: async (email, password) => {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error || !data.session) throw new Error("E-posta veya şifre hatalı");
    // Make sure the session is readable before hitting the API.
    await waitForSession();
    const user = await get().fetchProfile();
    if (!user) {
      // Auth succeeded but the app profile could not be loaded — surface it
      // instead of silently bouncing the user back to the login screen.
      throw new Error("Profil yüklenemedi. Lütfen tekrar deneyin.");
    }
  },

  register: async (email, password, companyName, fullName) => {
    // 1) Create the Supabase Auth user.
    const { data, error } = await supabase.auth.signUp({ email, password });
    if (error) throw new Error(error.message || "Kayıt başarısız");
    // 2) If email confirmation is on, no session is returned — the user must
    //    confirm, then sign in (provisioning happens on first login).
    if (!data.session) {
      throw new Error("Hesabınız oluşturuldu. Lütfen e-postanızı onaylayıp giriş yapın.");
    }
    await waitForSession();
    // Provision company + director row, and set the user straight from the
    // response (no /auth/me round-trip, no race).
    const user = await apiPost<User>("/auth/register", {
      company_name: companyName,
      full_name: fullName,
      email,
    });
    set({ user });
  },

  // CR-041: accept a teammate invite. Unlike register(), this attaches the user
  // to the INVITING company (the backend reads it from the invite), so no company
  // name is collected. Two entry modes:
  //   - "signup": brand-new user creates their Supabase Auth account here.
  //   - "signin": the user already created the account (e.g. had to confirm their
  //     email first) and now signs in before accepting.
  acceptInvite: async (token, email, password, fullName, mode) => {
    if (mode === "signup") {
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) throw new Error(error.message || "Kayıt başarısız");
      // Email confirmation on → no session. The user must confirm, then return
      // and sign in to accept (handled by the "signin" mode on the page).
      if (!data.session) {
        throw new Error(
          "Hesabınız oluşturuldu. Lütfen e-postanızı onaylayın, sonra bu sayfaya dönüp giriş yaparak daveti kabul edin."
        );
      }
    } else {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error || !data.session) throw new Error("E-posta veya şifre hatalı");
    }
    await waitForSession();
    // Provision the user into the inviting company and set them straight from the
    // response (no /auth/me round-trip, no race) — mirrors register().
    const user = await apiPost<User>(`/auth/invite/${token}/accept`, { full_name: fullName });
    set({ user });
  },

  logout: async () => {
    await supabase.auth.signOut();
    set({ user: null });
  },

  // Retries a few times to ride out the post-sign-in token-propagation race.
  fetchProfile: async (): Promise<User | null> => {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const { data } = await apiGet<User>("/auth/me");
        set({ user: data });
        return data;
      } catch {
        if (attempt < 2) {
          await sleep(250);
          continue;
        }
        set({ user: null });
        return null;
      }
    }
    return null;
  },
}));
