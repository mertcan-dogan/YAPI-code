import { apiGet } from "./api";

// Perf — a tiny shared GET cache so the global chrome (sidebar/command palette/
// notification bell) and the page components don't each fetch the same endpoint.
// Two layers:
//  1. in-flight dedup — concurrent identical GETs share one promise (the common
//     case when a page + its chrome mount together);
//  2. a short TTL result cache — a GET that resolves slightly before a sibling
//     fires (staggered mounts) still serves the cached result; also avoids
//     re-fetching the same list when navigating between pages within the window.
// A user-triggered refetch passes { force: true } to bypass + refresh the cache.
const TTL_MS = 30_000;

interface Entry {
  ts: number;
  data: unknown;
  meta: unknown;
}

const cache = new Map<string, Entry>();
const inflight = new Map<string, Promise<{ data: unknown; meta?: unknown }>>();

function keyOf(url: string, params?: Record<string, unknown>): string {
  return url + "|" + JSON.stringify(params ?? {});
}

export async function cachedGet<T = unknown>(
  url: string,
  params?: Record<string, unknown>,
  opts?: { force?: boolean; timeout?: number }
): Promise<{ data: T; meta?: unknown }> {
  const key = keyOf(url, params);

  if (!opts?.force) {
    const hit = cache.get(key);
    if (hit && Date.now() - hit.ts < TTL_MS) {
      return { data: hit.data as T, meta: hit.meta };
    }
    const pending = inflight.get(key);
    if (pending) return pending as Promise<{ data: T; meta?: unknown }>;
  }

  const p = apiGet<T>(url, params, opts?.timeout ? { timeout: opts.timeout } : undefined)
    .then((res) => {
      cache.set(key, { ts: Date.now(), data: res.data, meta: res.meta });
      inflight.delete(key);
      return res;
    })
    .catch((e) => {
      inflight.delete(key);
      throw e;
    });

  if (!opts?.force) inflight.set(key, p);
  return p;
}

/** Drop cached entries whose URL matches the predicate (call after a mutation). */
export function invalidate(pred: (url: string) => boolean): void {
  for (const k of [...cache.keys()]) {
    if (pred(k.split("|")[0])) cache.delete(k);
  }
}

/** Clear everything — used by the test setup between tests. */
export function clearRequestCache(): void {
  cache.clear();
  inflight.clear();
}
