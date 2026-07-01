import { beforeEach, describe, expect, it, vi } from "vitest";

// Perf — the shared GET cache must collapse the chrome + page fetching the same
// endpoint into ONE request, while a forced refetch still bypasses it.
const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("./api", () => ({ apiGet, baseURL: "" }));

import { cachedGet, clearRequestCache, invalidate } from "./requestCache";

beforeEach(() => {
  vi.clearAllMocks();
  clearRequestCache();
});

describe("cachedGet", () => {
  it("dedups concurrent identical GETs into one request", async () => {
    apiGet.mockResolvedValue({ data: [1, 2], meta: { total: 2 } });
    const [a, b, c] = await Promise.all([
      cachedGet("/projects"),
      cachedGet("/projects"),
      cachedGet("/projects"),
    ]);
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(a.data).toEqual([1, 2]);
    expect(b.data).toEqual([1, 2]);
    expect(c.data).toEqual([1, 2]);
  });

  it("serves a sequential second GET from the TTL cache (one request)", async () => {
    apiGet.mockResolvedValue({ data: "x", meta: null });
    await cachedGet("/approvals");
    await cachedGet("/approvals");
    expect(apiGet).toHaveBeenCalledTimes(1);
  });

  it("keys by params (different params → different requests)", async () => {
    apiGet.mockResolvedValue({ data: 1 });
    await cachedGet("/x", { a: 1 });
    await cachedGet("/x", { a: 2 });
    expect(apiGet).toHaveBeenCalledTimes(2);
  });

  it("force bypasses the cache and refreshes it", async () => {
    apiGet.mockResolvedValueOnce({ data: "old" }).mockResolvedValueOnce({ data: "new" });
    expect((await cachedGet("/p")).data).toBe("old");
    expect((await cachedGet("/p", undefined, { force: true })).data).toBe("new");
    expect(apiGet).toHaveBeenCalledTimes(2);
    // A later non-forced read sees the refreshed value, no new request.
    expect((await cachedGet("/p")).data).toBe("new");
    expect(apiGet).toHaveBeenCalledTimes(2);
  });

  it("invalidate() drops matching entries so the next read refetches", async () => {
    apiGet.mockResolvedValue({ data: 1 });
    await cachedGet("/projects");
    invalidate((url) => url === "/projects");
    await cachedGet("/projects");
    expect(apiGet).toHaveBeenCalledTimes(2);
  });

  it("does not cache a rejected request", async () => {
    apiGet.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce({ data: "ok" });
    await expect(cachedGet("/e")).rejects.toThrow("boom");
    expect((await cachedGet("/e")).data).toBe("ok");
    expect(apiGet).toHaveBeenCalledTimes(2);
  });
});
