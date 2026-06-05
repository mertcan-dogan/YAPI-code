import axios from "axios";
import { supabase } from "./supabase";

const baseURL = (import.meta.env.VITE_API_BASE_URL as string) ?? "http://localhost:8000/api/v1";

export const api = axios.create({ baseURL });

// Attach the Supabase JWT to every request (Section 3.1).
api.interceptors.request.use(async (config) => {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`;
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
    if (error.response?.status === 401) {
      // Session invalid — bounce to login.
      supabase.auth.signOut();
    }
    return Promise.reject(Object.assign(new Error(message), { field, code, status: error.response?.status }));
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
