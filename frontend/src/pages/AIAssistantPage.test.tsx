// CR-011-D — AIAssistantPage live SSE streaming.
// The page now drives the Yapı Agent chat from streamAgent (POST /ai/agent?stream=1)
// instead of the old non-stream apiPost + fake "thinking" timer. streamAgent is
// mocked so each test can deterministically push delta/step/final/error events and
// assert the UI: token-by-token answer, real-time step labels, the final answer
// with citation chips, and the graceful error message. We also assert the page no
// longer hits the non-stream /ai/agent endpoint.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import type { AgentResponse } from "@/types/agent";

const h = vi.hoisted(() => ({
  streamCalls: [] as { body: any; cb: any }[],
  apiGet: vi.fn(() => Promise.resolve({ data: [] as any[] })),
  apiPost: vi.fn(() => Promise.resolve({})),
  apiPut: vi.fn(() => Promise.resolve({})),
  apiDelete: vi.fn(() => Promise.resolve({})),
  aborted: 0,
}));

vi.mock("@/lib/agentStream", () => ({
  streamAgent: (body: any, cb: any) => {
    h.streamCalls.push({ body, cb });
    return () => {
      h.aborted += 1;
    };
  },
}));
vi.mock("@/lib/api", () => ({
  apiGet: h.apiGet,
  apiPost: h.apiPost,
  apiPut: h.apiPut,
  apiDelete: h.apiDelete,
  baseURL: "",
}));
vi.mock("@/hooks/useFetch", () => ({ useFetch: () => ({ data: [] }) }));
// supabase.ts calls createClient at import time (needs env); stub it so the page's
// transitive auth import doesn't blow up under jsdom.
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: () => Promise.resolve({ data: { session: null } }) } },
}));
vi.mock("@/store/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));
// Render markdown as raw text so token/answer assertions are stable.
vi.mock("@/components/MarkdownText", () => ({
  MarkdownText: ({ text }: { text: string }) => createElement("div", null, text),
}));
vi.mock("@/components/charts/AgentChart", () => ({
  AgentChart: () => createElement("div", { "data-testid": "chart" }),
}));

import AIAssistantPage from "./AIAssistantPage";

const FINAL: AgentResponse = {
  answer_markdown: "Akçansa ile toplam 4.500 ₺ harcandı.",
  charts: [],
  citations: [{ type: "cost_entry", id: "c1", label: "Akçansa — 4.000 ₺", deep_link: "/projects/x?highlight=1" }],
  tools_used: ["get_vendor_spend"],
  generated_at: "2026-06-19T08:00:00Z",
  row_counts: { get_vendor_spend: 1 },
  query_log_id: "q1",
  proposed_actions: [],
};

const wrap = () => render(createElement(MemoryRouter, null, createElement(AIAssistantPage)));

const submit = (text: string) => {
  fireEvent.change(screen.getByPlaceholderText("Sorunuzu yazın…"), { target: { value: text } });
  fireEvent.click(screen.getByLabelText("Gönder"));
};

// jsdom doesn't implement scrollIntoView (used by the auto-scroll effect).
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  h.streamCalls.length = 0;
  h.aborted = 0;
  vi.clearAllMocks();
  h.apiGet.mockResolvedValue({ data: [] });
  localStorage.clear();
});
afterEach(cleanup);

describe("AIAssistantPage live streaming (CR-011-D)", () => {
  it("submitting a question starts a stream with the mapped messages + project_id", () => {
    wrap();
    submit("Akçansa ne kadar?");

    expect(h.streamCalls).toHaveLength(1);
    const { body } = h.streamCalls[0];
    expect(body.messages).toEqual([{ role: "user", content: "Akçansa ne kadar?" }]);
    expect(body.project_id).toBeNull();
    // The user's turn shows immediately (also echoed in the conversation title).
    expect(screen.getAllByText("Akçansa ne kadar?").length).toBeGreaterThan(0);
    // The non-stream endpoint is no longer used for answering.
    expect(h.apiPost).not.toHaveBeenCalledWith("/ai/agent", expect.anything());
  });

  it("renders live tokens as they arrive, then the real step label", () => {
    wrap();
    submit("Akçansa ne kadar?");
    const cb = h.streamCalls[0].cb;

    act(() => cb.onDelta("Hesaplanıyor "));
    act(() => cb.onDelta("lütfen bekleyin"));
    expect(screen.getByText("Hesaplanıyor lütfen bekleyin")).toBeInTheDocument();

    // A step event clears the preamble preview and updates the indicator.
    act(() => cb.onStep("Tedarikçi harcamaları inceleniyor…", "get_vendor_spend"));
    expect(screen.getByText("Tedarikçi harcamaları inceleniyor…")).toBeInTheDocument();
    expect(screen.queryByText("Hesaplanıyor lütfen bekleyin")).not.toBeInTheDocument();
  });

  it("on final renders the answer + citation chip and stops the loading state", () => {
    wrap();
    submit("Akçansa ne kadar?");
    act(() => h.streamCalls[0].cb.onFinal(FINAL));

    expect(screen.getByText("Akçansa ile toplam 4.500 ₺ harcandı.")).toBeInTheDocument();
    expect(screen.getByText("Akçansa — 4.000 ₺")).toBeInTheDocument();
    // Send button is enabled again once a (typed) question can be sent.
    fireEvent.change(screen.getByPlaceholderText("Sorunuzu yazın…"), { target: { value: "tekrar" } });
    expect(screen.getByLabelText("Gönder")).not.toBeDisabled();
  });

  it("on error shows the graceful Turkish message, not a silent empty state", () => {
    wrap();
    submit("Akçansa ne kadar?");
    act(() => h.streamCalls[0].cb.onError(new Error("boom")));

    expect(screen.getByText("AI şu an kullanılamıyor.")).toBeInTheDocument();
  });

  it("ignores a new submit while a stream is in flight (loading guard)", () => {
    wrap();
    submit("ilk soru");
    // While loading, the composer is disabled and a second ask is a no-op.
    expect(screen.getByLabelText("Gönder")).toBeDisabled();
    fireEvent.submit(screen.getByPlaceholderText("Sorunuzu yazın…").closest("form")!);
    expect(h.streamCalls).toHaveLength(1);
  });

  it("aborts the in-flight stream when the page unmounts", () => {
    const { unmount } = wrap();
    submit("Akçansa ne kadar?");
    expect(h.aborted).toBe(0);
    unmount();
    expect(h.aborted).toBe(1);
  });

  it("persists the user turn to the server before the answer arrives", async () => {
    wrap();
    submit("kalıcı mı?");
    // syncConversation PUTs the conversation with the user message immediately.
    await waitFor(() =>
      expect(h.apiPut).toHaveBeenCalledWith(
        expect.stringContaining("/ai/conversations/"),
        expect.objectContaining({
          messages: [{ role: "user", text: "kalıcı mı?" }],
        })
      )
    );
  });

  // Gap: the INITIAL_STEP preamble must show right after submit, before any
  // server event arrives — otherwise the user sees a blank spinner.
  it("shows the initial Turkish step label before the first stream event", () => {
    wrap();
    submit("Akçansa ne kadar?");
    // No delta/step pushed yet → the preamble indicator is visible.
    expect(screen.getByText("Soru anlaşılıyor…")).toBeInTheDocument();
  });

  // Gap: an empty answer_markdown must degrade to the Turkish "no data" copy,
  // never an empty AI bubble.
  it("on final with an empty answer renders the Turkish no-data fallback", () => {
    wrap();
    submit("boş cevap?");
    act(() => h.streamCalls[0].cb.onFinal({ ...FINAL, answer_markdown: "" }));

    expect(screen.getByText("Bu konuda veri bulunamadı.")).toBeInTheDocument();
  });

  // Gap: after one answer completes the loading guard must release AND the abort
  // ref must be re-armed — a follow-up question starts a fresh second stream and
  // the new turn is appended to the same conversation (no loss of history).
  it("a follow-up question after completion starts a fresh stream", () => {
    wrap();
    submit("ilk soru");
    act(() => h.streamCalls[0].cb.onFinal(FINAL));
    // The first answer is on screen and the composer is usable again.
    expect(screen.getByText("Akçansa ile toplam 4.500 ₺ harcandı.")).toBeInTheDocument();

    submit("ikinci soru");
    expect(h.streamCalls).toHaveLength(2);
    // The follow-up carries the full prior turns as mapped Anthropic messages.
    expect(h.streamCalls[1].body.messages).toEqual([
      { role: "user", content: "ilk soru" },
      { role: "assistant", content: "Akçansa ile toplam 4.500 ₺ harcandı." },
      { role: "user", content: "ikinci soru" },
    ]);
  });

  // Gap: an empty-string step label must NOT blank the indicator — the prior
  // label (or preamble) is kept. Guards the `if (label)` branch in onStep.
  it("an empty step label keeps the current indicator instead of clearing it", () => {
    wrap();
    submit("Akçansa ne kadar?");
    const cb = h.streamCalls[0].cb;
    act(() => cb.onStep("Veriler çekiliyor…", "get_vendor_spend"));
    act(() => cb.onStep("", "noop"));
    // Empty label is ignored; the previous real label survives.
    expect(screen.getByText("Veriler çekiliyor…")).toBeInTheDocument();
  });
});

// Cowork-style collapsible thinking steps: live while running, collapsed group
// on completion, each past turn re-expandable, each step row individually open.
describe("AIAssistantPage agent steps (Cowork-style collapse)", () => {
  it("shows steps live (expanded) while running, then collapses on completion", () => {
    wrap();
    submit("Akçansa ne kadar?");
    const cb = h.streamCalls[0].cb;

    // Two tool steps arrive — the live panel is auto-expanded.
    act(() => cb.onStep("Düşünüyorum…", ""));
    act(() => cb.onStep("Tedarikçi harcamaları inceleniyor…", "get_vendor_spend"));
    expect(screen.getByText("İşlem adımları")).toBeInTheDocument();
    // The live one-line comments are visible while running.
    expect(screen.getByText("Tedarikçi harcamaları inceleniyor…")).toBeInTheDocument();

    // On final the live panel is gone and the steps collapse into a group toggle;
    // the per-step comment is hidden until the group is re-expanded.
    act(() => cb.onFinal(FINAL));
    expect(screen.queryByText("İşlem adımları")).not.toBeInTheDocument();
    expect(screen.getByText("2 adım tamamlandı")).toBeInTheDocument();
    expect(screen.queryByText("Tedarikçi harcamaları inceleniyor…")).not.toBeInTheDocument();
  });

  it("expands a collapsed group, then a single step row reveals its detail", () => {
    wrap();
    submit("Akçansa ne kadar?");
    const cb = h.streamCalls[0].cb;
    act(() => cb.onStep("Tedarikçi harcamaları inceleniyor…", "get_vendor_spend"));
    act(() => cb.onFinal(FINAL));

    // Collapsed → expand the group toggle to reveal the step rows.
    fireEvent.click(screen.getByText("1 adım tamamlandı"));
    expect(screen.getByText("Tedarikçi harcamaları inceleniyor…")).toBeInTheDocument();

    // Each step row is itself collapsible — its detail (raw tool name + row count)
    // is hidden until the row header is clicked.
    expect(screen.queryByText("get_vendor_spend")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Tedarikçi harcamaları okundu"));
    expect(screen.getByText("get_vendor_spend")).toBeInTheDocument();
    expect(screen.getByText("1 kayıt okundu")).toBeInTheDocument();
  });

  it("keeps each past turn's step group, expandable independently", () => {
    wrap();
    // Turn 1 — one step, then complete.
    submit("ilk soru");
    act(() => h.streamCalls[0].cb.onStep("İlk turun adımı…", "get_vendor_spend"));
    act(() => h.streamCalls[0].cb.onFinal(FINAL));

    // Turn 2 — a different step, then complete.
    submit("ikinci soru");
    act(() => h.streamCalls[1].cb.onStep("İkinci turun adımı…", "get_cashflow"));
    act(() =>
      h.streamCalls[1].cb.onFinal({ ...FINAL, answer_markdown: "İkinci yanıt.", tools_used: ["get_cashflow"] })
    );

    // Both past turns keep their own collapsed group; expanding the FIRST turn
    // reveals only its step, independent of the second.
    const groups = screen.getAllByText("1 adım tamamlandı");
    expect(groups).toHaveLength(2);
    fireEvent.click(groups[0]);
    expect(screen.getByText("İlk turun adımı…")).toBeInTheDocument();
    expect(screen.queryByText("İkinci turun adımı…")).not.toBeInTheDocument();
  });

  it("renders no step group when the answer used no tools (graceful zero steps)", () => {
    wrap();
    submit("merhaba");
    // No step events; final carries no tools.
    act(() => h.streamCalls[0].cb.onFinal({ ...FINAL, tools_used: [], row_counts: {} }));

    expect(screen.getByText("Akçansa ile toplam 4.500 ₺ harcandı.")).toBeInTheDocument();
    expect(screen.queryByText(/adım tamamlandı/)).not.toBeInTheDocument();
    expect(screen.queryByText(/araç kullanıldı/)).not.toBeInTheDocument();
  });

  // Gap: when EVERY recorded step ran a tool (and there is more than one), the
  // collapsed group summarises by tool count ("N araç kullanıldı") rather than
  // step count. Only this branch tells the user how many tools the agent hit; the
  // other tests only ever produce "N adım tamamlandı" (or assert its absence).
  it("summarises an all-tool turn as 'N araç kullanıldı', not step count", () => {
    wrap();
    submit("Akçansa ne kadar?");
    const cb = h.streamCalls[0].cb;
    // Two steps, BOTH carrying a tool (no reasoning/thinking step in between).
    act(() => cb.onStep("Tedarikçi harcamaları inceleniyor…", "get_vendor_spend"));
    act(() => cb.onStep("Nakit akışı hesaplanıyor…", "get_cashflow"));
    act(() =>
      cb.onFinal({
        ...FINAL,
        tools_used: ["get_vendor_spend", "get_cashflow"],
        row_counts: { get_vendor_spend: 1, get_cashflow: 3 },
      })
    );

    // Tool-count summary wins; the step-count phrasing must NOT appear.
    expect(screen.getByText("2 araç kullanıldı")).toBeInTheDocument();
    expect(screen.queryByText(/adım tamamlandı/)).not.toBeInTheDocument();
  });
});

// CR-035 — Rapor Stüdyosu hand-off: a saved-report Q&A grounds the session in a
// report_id (threaded into every stream body); a studioIntent tunes the input hint.
describe("AIAssistantPage Rapor Stüdyosu hand-off (CR-035)", () => {
  const wrapWithState = (state: any) =>
    render(
      createElement(
        MemoryRouter,
        { initialEntries: [{ pathname: "/ai-assistant", state }] },
        createElement(AIAssistantPage)
      )
    );

  it("threads report_id from location.state into the stream body", () => {
    wrapWithState({ report_id: "rep-9" });
    submit("bu raporu özetle");
    expect(h.streamCalls).toHaveLength(1);
    expect(h.streamCalls[0].body.report_id).toBe("rep-9");
  });

  it("shows the studio-intent placeholder hint when handed studioIntent", () => {
    wrapWithState({ studioIntent: "report" });
    expect(
      screen.getByPlaceholderText("Ne görmek istediğinizi yazın — örn. 'daire tipine göre kâr/zarar raporu yap'")
    ).toBeInTheDocument();
  });

  it("defaults report_id to null when no hand-off state is present", () => {
    wrap();
    submit("normal soru");
    expect(h.streamCalls[0].body.report_id).toBeNull();
  });
});
