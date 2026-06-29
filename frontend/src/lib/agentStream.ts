// CR-011-D §4.1 — token-streaming client for POST /ai/agent?stream=1.
//
// EventSource cannot POST, so we use fetch + a ReadableStream reader and parse
// the SSE frames ourselves. Events: `delta` (live answer tokens), `step` (a tool
// started — drives the real-time step indicator), `final` (the full structured
// AgentResponse). If the stream cannot even be opened we fall back to the
// non-stream JSON endpoint so the answer is never lost (§1.1). We do NOT re-run
// on a mid-stream break (the server already degrades internally) to avoid
// duplicate side effects from any proposed action.
import type { AgentResponse } from "@/types/agent";
import { apiPost, baseURL } from "./api";
import { supabase } from "./supabase";

// CR-011 rich steps (PART A/B): extra per-step detail the `step` event now
// carries — the cleaned tool args, the model's pre-tool narration, and (when the
// thinking flag is on) its reasoning text. All optional/additive.
export interface StepDetail {
  input?: Record<string, unknown> | null;
  note?: string | null;
  thinking?: string | null;
}

export interface StreamCallbacks {
  onDelta?: (text: string) => void;
  // `detail` is additive — older callers that take (label, tool) keep working.
  onStep?: (label: string, tool: string, detail?: StepDetail) => void;
  onFinal: (res: AgentResponse) => void;
  onError?: (e: unknown) => void;
}

export interface StreamBody {
  messages: { role: string; content: string }[];
  project_id?: string | null;
  scope?: string | null;
  // CR-035 (additive): when set, the backend grounds a READ-ONLY Q&A in this saved
  // report. Forwarded verbatim on both the SSE POST and the non-stream fallback.
  report_id?: string | null;
  // CR-039 (additive): the active authoring draft the user is refining
  // ({kind, spec|widgets, title}). Forwarded verbatim so the agent edits the real
  // spec. Request-only; the agent still writes nothing.
  draft?: Record<string, unknown> | null;
}

function parseFrame(frame: string): { event?: string; data?: string } {
  let event: string | undefined;
  let data: string | undefined;
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data = (data ? data + "\n" : "") + line.slice(5).trim();
  }
  return { event, data };
}

/**
 * Start a streaming agent request. Returns an `abort` function (call it on
 * unmount / new question). Callbacks are invoked as events arrive; exactly one
 * `onFinal` fires on success (streamed or via the non-stream fallback).
 */
export function streamAgent(body: StreamBody, cb: StreamCallbacks): () => void {
  const controller = new AbortController();

  (async () => {
    let received = false;
    try {
      let token: string | undefined;
      try {
        const {
          data: { session },
        } = await supabase.auth.getSession();
        token = session?.access_token;
      } catch {
        /* no session — let the request 401 and fall back */
      }

      const resp = await fetch(`${baseURL}/ai/agent?stream=1`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) throw new Error(`stream http ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let finalSeen = false;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const { event, data } = parseFrame(buf.slice(0, idx));
          buf = buf.slice(idx + 2);
          if (!data) continue;
          received = true;
          try {
            const parsed = JSON.parse(data);
            if (event === "delta") cb.onDelta?.(parsed.text ?? "");
            else if (event === "step")
              cb.onStep?.(parsed.label ?? "", parsed.tool ?? "", {
                input: parsed.input,
                note: parsed.note,
                thinking: parsed.thinking,
              });
            else if (event === "final") {
              cb.onFinal(parsed as AgentResponse);
              finalSeen = true;
            }
          } catch {
            /* ignore a malformed frame */
          }
        }
      }
      if (!finalSeen) throw new Error("stream ended without final");
    } catch (e) {
      if (controller.signal.aborted) return;
      // Connection never produced events → fall back to the non-stream endpoint
      // (never lose the answer). If the stream had started but broke mid-flight,
      // surface an error instead of re-running (avoids duplicate proposals).
      if (!received) {
        try {
          const res = await apiPost<AgentResponse>("/ai/agent", body);
          cb.onFinal(res);
          return;
        } catch (e2) {
          cb.onError?.(e2);
          return;
        }
      }
      cb.onError?.(e);
    }
  })();

  return () => controller.abort();
}
