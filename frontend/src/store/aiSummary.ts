import { create } from "zustand";
import { persist } from "zustand/middleware";

// CR-005-G: cache AI summaries so they run once per page (per project) instead of
// on every mount/navigation. Persisted to localStorage so the cache survives an
// F5 reload. Content is stored as a string — array payloads (e.g. the dashboard
// briefing) are JSON-serialised by the caller.
interface CachedSummary {
  content: string;
  generatedAt: string; // ISO datetime string
  projectId?: string;
}

interface AISummaryState {
  summaries: Record<string, CachedSummary>;
  setSummary: (key: string, content: string, projectId?: string) => void;
  getSummary: (key: string) => CachedSummary | null;
  clearSummary: (key: string) => void;
}

export const useAISummaryStore = create<AISummaryState>()(
  persist(
    (set, get) => ({
      summaries: {},
      setSummary: (key, content, projectId) =>
        set((s) => ({
          summaries: {
            ...s.summaries,
            [key]: { content, generatedAt: new Date().toISOString(), projectId },
          },
        })),
      getSummary: (key) => get().summaries[key] ?? null,
      clearSummary: (key) =>
        set((s) => {
          const next = { ...s.summaries };
          delete next[key];
          return { summaries: next };
        }),
    }),
    { name: "yapi-ai-summaries" }
  )
);
