import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

// Generic GET hook with loading/error and a refetch.
export function useFetch<T = any>(url: string | null, params?: Record<string, unknown>) {
  const [data, setData] = useState<T | null>(null);
  const [meta, setMeta] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const paramsKey = JSON.stringify(params ?? {});

  const refetch = useCallback(async () => {
    if (!url) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<T>(url, params);
      setData(res.data);
      setMeta(res.meta);
    } catch (e: any) {
      setError(e.message ?? "Yükleme hatası");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, paramsKey]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, meta, loading, error, refetch, setData };
}
