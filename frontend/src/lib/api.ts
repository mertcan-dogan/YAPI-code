import axios from "axios";
import { supabase } from "./supabase";

const baseURL = (import.meta.env.VITE_API_BASE_URL as string) ?? "http://localhost:8000/api/v1";

export const api = axios.create({ baseURL });

const DEBUG_AUTH = import.meta.env.DEV || import.meta.env.VITE_DEBUG_AUTH === "1";

function algOf(jwtToken: string): string {
  try {
    return JSON.parse(atob(jwtToken.split(".")[0])).alg ?? "?";
  } catch {
    return "?";
  }
}

// Attach the Supabase JWT to every request (Section 3.1).
api.interceptors.request.use(async (config) => {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
    if (DEBUG_AUTH) console.debug(`[auth] → ${config.url} attaching token alg=${algOf(token)} len=${token.length}`);
  } else if (DEBUG_AUTH) {
    console.warn(`[auth] → ${config.url} NO session token to attach (getSession returned null)`);
  }
  return config;
});

// Normalise the Section-C error envelope into an Error with a Turkish message.
api.interceptors.response.use(
  (res) => res,
  (error) => {
    const env = error.response?.data;
    const message = env?.error?.message ?? "Beklenmeyen bir hata oluştu";
    const field = env?.error?.field;
    const code = env?.error?.code;
    const status = error.response?.status;
    if (DEBUG_AUTH && status === 401) {
      console.warn(`[auth] ← ${error.config?.url} 401 ${code ?? ""}: ${message}`);
    }
    // Only force sign-out on a genuine token rejection — not on /auth/me probes,
    // so we never wipe a freshly created session before it is usable.
    if (status === 401 && !String(error.config?.url ?? "").includes("/auth/me")) {
      supabase.auth.signOut();
    }
    return Promise.reject(Object.assign(new Error(message), { field, code, status }));
  }
);

// Helper that unwraps { success, data, meta }.
export async function apiGet<T = any>(url: string, params?: Record<string, unknown>): Promise<{ data: T; meta?: any }> {
  const res = await api.get(url, { params });
  return { data: res.data.data, meta: res.data.meta };
}

export async function apiPost<T = any>(url: string, body?: unknown): Promise<T> {
  const res = await api.post(url, body);
  return res.data.data;
}

export async function apiPut<T = any>(url: string, body?: unknown): Promise<T> {
  const res = await api.put(url, body);
  return res.data.data;
}

export async function apiDelete<T = any>(url: string): Promise<T> {
  const res = await api.delete(url);
  return res.data.data;
}
