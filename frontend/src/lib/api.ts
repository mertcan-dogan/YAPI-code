import axios from "axios";
import { supabase } from "./supabase";
import { cachedGet, invalidate } from "./requestCache";
import type {
  Dashboard,
  DashboardListItem,
  DashboardPatchBody,
  DashboardRunResult,
  DashboardSaveBody,
  ReportListItem,
  ReportOut,
  ReportPatchBody,
  ReportSaveBody,
  RunResult,
  StudioCatalog,
  StudioSpec,
} from "@/types/studio";
import type {
  SkillCreateBody,
  SkillDownloadResult,
  SkillListItem,
  SkillOut,
  SkillPatchBody,
  SkillRunOut,
  SkillRunResult,
} from "@/types/skill";

export const baseURL = (import.meta.env.VITE_API_URL as string) || "https://yapi-code-production.up.railway.app/api/v1";

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
    // A timeout/network abort has no response — give it a clear, retryable message.
    const isTimeout = error.code === "ECONNABORTED" || /timeout/i.test(error.message ?? "");
    const message =
      env?.error?.message ??
      (isTimeout ? "İstek zaman aşımına uğradı. Lütfen tekrar deneyin." : "Beklenmeyen bir hata oluştu");
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

// Helper that unwraps { success, data, meta }. An optional `timeout` (ms) bounds
// a hanging request so the caller can surface a retryable error instead of
// spinning forever (axios rejects with ECONNABORTED on timeout).
export async function apiGet<T = any>(
  url: string,
  params?: Record<string, unknown>,
  config?: { timeout?: number }
): Promise<{ data: T; meta?: any }> {
  const res = await api.get(url, { params, ...config });
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

export async function apiPatch<T = any>(url: string, body?: unknown): Promise<T> {
  const res = await api.patch(url, body);
  return res.data.data;
}

export async function apiDelete<T = any>(url: string): Promise<T> {
  const res = await api.delete(url);
  return res.data.data;
}

// Blob download helper — the Supabase JWT is attached by the request interceptor,
// so this works for authenticated file endpoints (window.open can't carry the
// token). Returns the raw Blob; the caller triggers the browser download.
export async function apiPostBlob(
  url: string,
  body?: unknown,
  params?: Record<string, unknown>
): Promise<Blob> {
  const res = await api.post(url, body, { responseType: "blob", params });
  return res.data as Blob;
}

// CR-033 — Report Studio. Grouped client calls against the FIXED /studio contract.
// catalog is cached (no per-company data); every mutation invalidates the cached
// /studio/reports list so the list view re-fetches on next mount.
const REPORTS_PREFIX = "/studio/reports";
const dropReportsCache = () => invalidate((url) => url.startsWith(REPORTS_PREFIX));
const DASHBOARDS_PREFIX = "/studio/dashboards";
const dropDashboardsCache = () => invalidate((url) => url.startsWith(DASHBOARDS_PREFIX));

export const studio = {
  catalog: () => cachedGet<StudioCatalog>("/studio/catalog").then((r) => r.data),
  run: (spec: StudioSpec) => apiPost<RunResult>("/studio/run", spec),
  listReports: (q?: string) =>
    cachedGet<ReportListItem[]>("/studio/reports", q ? { q } : undefined).then((r) => r.data),
  getReport: (id: string) => apiGet<ReportOut>(`/studio/reports/${id}`).then((r) => r.data),
  createReport: async (body: ReportSaveBody) => {
    const r = await apiPost<ReportOut>("/studio/reports", body);
    dropReportsCache();
    return r;
  },
  updateReport: async (id: string, body: ReportPatchBody) => {
    const r = await apiPatch<ReportOut>(`/studio/reports/${id}`, body);
    dropReportsCache();
    return r;
  },
  deleteReport: async (id: string) => {
    const r = await apiDelete<{ deleted: boolean }>(`/studio/reports/${id}`);
    dropReportsCache();
    return r;
  },
  duplicateReport: async (id: string) => {
    const r = await apiPost<ReportOut>(`/studio/reports/${id}/duplicate`);
    dropReportsCache();
    return r;
  },
  runReport: (id: string) => apiPost<RunResult>(`/studio/reports/${id}/run`),
  exportReportBlob: (id: string, format: "pdf" | "xlsx" | "csv") =>
    apiPostBlob(`/studio/reports/${id}/export`, undefined, { format }),

  // CR-034 — panolar (dashboards). Same caching discipline as reports: the list is
  // cached via requestCache and every mutation drops the dashboards cache so the
  // list view re-fetches on next mount. The catalog stays shared/cached above.
  listDashboards: (q?: string) =>
    cachedGet<DashboardListItem[]>("/studio/dashboards", q ? { q } : undefined).then((r) => r.data),
  getDashboard: (id: string) => apiGet<Dashboard>(`/studio/dashboards/${id}`).then((r) => r.data),
  createDashboard: async (body: DashboardSaveBody) => {
    const r = await apiPost<Dashboard>("/studio/dashboards", body);
    dropDashboardsCache();
    return r;
  },
  updateDashboard: async (id: string, body: DashboardPatchBody) => {
    const r = await apiPatch<Dashboard>(`/studio/dashboards/${id}`, body);
    dropDashboardsCache();
    return r;
  },
  deleteDashboard: async (id: string) => {
    const r = await apiDelete<{ deleted: boolean }>(`/studio/dashboards/${id}`);
    dropDashboardsCache();
    return r;
  },
  duplicateDashboard: async (id: string) => {
    const r = await apiPost<Dashboard>(`/studio/dashboards/${id}/duplicate`);
    dropDashboardsCache();
    return r;
  },
  runDashboard: (id: string) => apiPost<DashboardRunResult>(`/studio/dashboards/${id}/run`),
  exportDashboardBlob: (id: string, format: "pdf" | "xlsx") =>
    apiPostBlob(`/studio/dashboards/${id}/export`, undefined, { format }),
};

// CR-044 — Beceriler (Skills). Same caching discipline as studio reports/dashboards:
// the list is cached via requestCache and every mutation drops the cache so the
// Uygulamalar list re-fetches on next mount. Running a skill also drops the cache —
// it is read-only over business data but it advances the skill's last_run_at, which
// the list surfaces, so the cached list would otherwise show a stale value.
const SKILLS_PREFIX = "/skills";
const dropSkillsCache = () => invalidate((url) => url.startsWith(SKILLS_PREFIX));

export const skills = {
  listSkills: (q?: string) =>
    cachedGet<SkillListItem[]>("/skills", q ? { q } : undefined).then((r) => r.data),
  getSkill: (id: string) => apiGet<SkillOut>(`/skills/${id}`).then((r) => r.data),
  createSkill: async (body: SkillCreateBody) => {
    const r = await apiPost<SkillOut>("/skills", body);
    dropSkillsCache();
    return r;
  },
  updateSkill: async (id: string, body: SkillPatchBody) => {
    const r = await apiPut<SkillOut>(`/skills/${id}`, body);
    dropSkillsCache();
    return r;
  },
  deleteSkill: async (id: string) => {
    const r = await apiDelete<{ ok: boolean }>(`/skills/${id}`);
    dropSkillsCache();
    return r;
  },
  // Run the skill: the engine batch-runs the plan's specs, builds the file, stores
  // it in the private bucket, and returns a short-lived signed download_url. Drops
  // the list cache so the row's last_run_at refreshes on next mount.
  runSkill: async (id: string) => {
    const r = await apiPost<SkillRunResult>(`/skills/${id}/run`);
    dropSkillsCache();
    return r;
  },
  listSkillRuns: (id: string) => apiGet<SkillRunOut[]>(`/skills/${id}/runs`).then((r) => r.data),
  // Re-sign a past run's file for re-download (company-scoped).
  downloadSkillFile: (runId: string) =>
    apiPost<SkillDownloadResult>(`/skills/runs/${runId}/download`),
};
