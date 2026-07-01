import { afterEach, describe, expect, it, vi } from "vitest";

// CR-011-E — unit test for the SSE streaming client: it parses delta/step/final
// frames off a ReadableStream and falls back to the non-stream endpoint when the
// stream cannot be opened (never lose the answer; no re-run on a mid-stream break).
const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }));

vi.mock("./api", () => ({ apiPost, baseURL: "http://test/api/v1" }));
vi.mock("./supabase", () => ({
  supabase: { auth: { getSession: vi.fn(() => Promise.resolve({ data: { session: { access_token: "tok" } } })) } },
}));

import { streamAgent } from "./agentStream";

function streamBody(frames: string): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(c) {
      c.enqueue(new TextEncoder().encode(frames));
      c.close();
    },
  });
}

async function until(fn: () => boolean, tries = 100) {
  for (let i = 0; i < tries && !fn(); i++) await new Promise((r) => setTimeout(r, 0));
}

afterEach(() => vi.clearAllMocks());

describe("streamAgent", () => {
  it("parses delta / step / final frames and invokes the callbacks", async () => {
    const frames =
      'event: delta\ndata: {"text":"Mer"}\n\n' +
      'event: delta\ndata: {"text":"haba"}\n\n' +
      'event: step\ndata: {"tool":"get_vendor_spend","label":"Tedarikçi…","input":{"vendor_name":"Akçansa"},"note":"tarıyorum","thinking":"düşünce"}\n\n' +
      'event: final\ndata: {"answer_markdown":"Merhaba","charts":[],"citations":[],"tools_used":[],"generated_at":"t","proposed_actions":[]}\n\n';
    (globalThis as any).fetch = vi.fn(() => Promise.resolve({ ok: true, body: streamBody(frames) }));

    const onDelta = vi.fn();
    const onStep = vi.fn();
    const onFinal = vi.fn();
    streamAgent({ messages: [{ role: "user", content: "x" }] }, { onDelta, onStep, onFinal });

    await until(() => onFinal.mock.calls.length > 0);
    expect(onDelta).toHaveBeenNthCalledWith(1, "Mer");
    expect(onDelta).toHaveBeenNthCalledWith(2, "haba");
    // CR-011 rich steps: the step detail (cleaned args, narration, thinking)
    // is passed through as the additive 3rd arg.
    expect(onStep).toHaveBeenCalledWith("Tedarikçi…", "get_vendor_spend", {
      input: { vendor_name: "Akçansa" },
      note: "tarıyorum",
      thinking: "düşünce",
    });
    expect(onFinal).toHaveBeenCalledWith(expect.objectContaining({ answer_markdown: "Merhaba" }));
    // The auth token was attached.
    const [, init] = (globalThis as any).fetch.mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("falls back to the non-stream endpoint when the stream cannot open", async () => {
    (globalThis as any).fetch = vi.fn(() => Promise.reject(new Error("network down")));
    apiPost.mockResolvedValueOnce({ answer_markdown: "Yedek yanıt", proposed_actions: [] });

    const onFinal = vi.fn();
    const onError = vi.fn();
    streamAgent({ messages: [{ role: "user", content: "x" }] }, { onFinal, onError });

    await until(() => onFinal.mock.calls.length > 0 || onError.mock.calls.length > 0);
    expect(apiPost).toHaveBeenCalledWith("/ai/agent", expect.objectContaining({ messages: expect.any(Array) }));
    expect(onFinal).toHaveBeenCalledWith(expect.objectContaining({ answer_markdown: "Yedek yanıt" }));
    expect(onError).not.toHaveBeenCalled();
  });

  it("does NOT re-run (no fallback) when the stream breaks mid-flight", async () => {
    // A body that yields one delta frame then errors → events were received, so
    // we must NOT re-run (avoids duplicate proposals); we surface onError. Use
    // pull() so the chunk is delivered on the first read BEFORE the error (an
    // error in start() would discard the queued chunk).
    let pulls = 0;
    const body = new ReadableStream({
      pull(c) {
        pulls += 1;
        if (pulls === 1) c.enqueue(new TextEncoder().encode('event: delta\ndata: {"text":"yarım"}\n\n'));
        else c.error(new Error("broke"));
      },
    });
    (globalThis as any).fetch = vi.fn(() => Promise.resolve({ ok: true, body }));

    const onDelta = vi.fn();
    const onFinal = vi.fn();
    const onError = vi.fn();
    streamAgent({ messages: [{ role: "user", content: "x" }] }, { onDelta, onFinal, onError });

    await until(() => onError.mock.calls.length > 0);
    expect(onDelta).toHaveBeenCalledWith("yarım");
    expect(apiPost).not.toHaveBeenCalled(); // no re-run
    expect(onFinal).not.toHaveBeenCalled();
  });
});
