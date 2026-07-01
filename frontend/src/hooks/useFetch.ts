import { useCallback, useEffect, useState } from "react";
import { cachedGet } from "@/lib/requestCache";

// Generic GET hook with loading/error and a refetch.
// Perf: the initial load goes through the shared request cache (so a page and the
// global chrome that hit the same endpoint share ONE request). A user-triggered
// refetch() forces a fresh fetch (and refreshes the cache).
export function useFetch<T = any>(
  url: string | null,
  params?: Record<string, unknown>,
  opts?: { timeout?: number }
) {
  const [data, setData] = useState<T | null>(null);
  const [meta, setMeta] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const paramsKey = JSON.stringify(params ?? {});
  const timeout = opts?.timeout;

  const load = useCallback(
    async (force: boolean) => {
      if (!url) return;
      setLoading(true);
      setError(null);
      try {
        // `timeout` bounds a hanging request so the page can show LoadError+retry
        // instead of an infinite skeleton (silent-load-failure).
        const res = await cachedGet<T>(url, params, { force, timeout });
        setData(res.data);
        setMeta(res.meta ?? null);
      } catch (e: any) {
        setError(e.message ?? "Yükleme hatası");
      } finally {
        setLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [url, paramsKey, timeout]
  );

  useEffect(() => {
    load(false);
  }, [load]);

  const refetch = useCallback(() => load(true), [load]);

  return { data, meta, loading, error, refetch, setData };
}
