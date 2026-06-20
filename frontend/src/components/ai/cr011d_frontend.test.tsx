import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentResponse } from "@/types/agent";

// CR-011-D — streaming UI, unified rail, scoped dock, proposed-action card.
// streamAgent is mocked so tests drive delta/step/final callbacks deterministically.
const { streamCalls, apiPut, apiPostMock, apiPostExport, toastSuccess, toastError, mockAuth } = vi.hoisted(() => ({
  streamCalls: [] as { body: any; cb: any }[],
  apiPut: vi.fn(() => Promise.resolve({})),
  apiPostMock: vi.fn(() => Promise.resolve({})),
  apiPostExport: vi.fn(() => Promise.resolve({ data: new Blob() })),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  mockAuth: { user: { role: "director" } as { role: string } | null },
}));

vi.mock("@/lib/agentStream", () => ({
  streamAgent: (body: any, cb: any) => {
    streamCalls.push({ body, cb });
    return () => {};
  },
}));
vi.mock("@/store/toast", () => ({
  toast: { success: toastSuccess, error: toastError, info: vi.fn(), warning: vi.fn() },
}));
vi.mock("@/lib/api", () => ({
  apiPut,
  apiPost: apiPostMock,
  api: { post: apiPostExport },
  baseURL: "",
}));
vi.mock("@/store/auth", () => ({ useAuth: () => mockAuth }));

import { AskAgentDrawer } from "@/components/dashboard/AskAgentDrawer";
import { ScopedAgentDock } from "@/components/dashboard/ScopedAgentDock";
import { YapiAIRail } from "@/components/dashboard/YapiAIRail";
import { ProposedActionCard } from "@/components/ai/ProposedActionCard";

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

const FINAL: AgentResponse = {
  answer_markdown: "Akçansa ile toplam **4.500 ₺** harcandı.",
  charts: [],
  citations: [{ type: "cost_entry", id: "c1", label: "Akçansa — 4.000 ₺", deep_link: "/projects/x/dashboard?highlight=1" }],
  tools_used: ["get_vendor_spend"],
  generated_at: "2026-06-19T08:00:00Z",
  row_counts: { get_vendor_spend: 1 },
  query_log_id: "q1",
  proposed_actions: [],
};

beforeEach(() => {
  streamCalls.length = 0;
  vi.clearAllMocks();
  mockAuth.user = { role: "director" };
});
afterEach(() => vi.clearAllMocks());

describe("AskAgentDrawer streaming (CR-011-D)", () => {
  it("streams live tokens, then renders the final answer + citation + export", () => {
    wrap(<AskAgentDrawer question="Akçansa ne kadar?" onClose={() => {}} />);

    // The stream was started with the question.
    expect(streamCalls).toHaveLength(1);
    expect(streamCalls[0].body.messages[0].content).toBe("Akçansa ne kadar?");
    const cb = streamCalls[0].cb;

    // Live tokens render as they arrive.
    act(() => cb.onDelta("Hesaplanıyor "));
    act(() => cb.onDelta("lütfen bekleyin"));
    expect(screen.getByText(/Hesaplanıyor lütfen bekleyin/)).toBeInTheDocument();

    // A step event clears the preamble preview and updates the indicator.
    act(() => cb.onStep("Tedarikçi harcamaları inceleniyor…", "get_vendor_spend"));
    expect(screen.getByText("Tedarikçi harcamaları inceleniyor…")).toBeInTheDocument();

    // Final payload renders the answer, citation chip and export control.
    act(() => cb.onFinal(FINAL));
    expect(screen.getByText(/Akçansa ile toplam/)).toBeInTheDocument();
    expect(screen.getByText("Akçansa — 4.000 ₺")).toBeInTheDocument();
    expect(screen.getByText("Dışa aktar")).toBeInTheDocument();
    expect(screen.getByText("AI nasıl çalıştı?")).toBeInTheDocument();
  });

  it("renders a proposed-action Onayla/Reddet card from the final payload", () => {
    wrap(<AskAgentDrawer question="bana hatırlat" onClose={() => {}} />);
    act(() =>
      streamCalls[0].cb.onFinal({
        ...FINAL,
        citations: [],
        proposed_actions: [
          { request_id: "r1", kind: "agent_reminder", kind_label: "Hatırlatıcı (AI önerisi)", description: "Ara beni", status: "pending", deep_link: "/approvals" },
        ],
      })
    );
    expect(screen.getByText(/Yapı AI şunu öneriyor/)).toBeInTheDocument();
    expect(screen.getByText("Onayla")).toBeInTheDocument();
  });
});

describe("ScopedAgentDock (CR-011-D / Item 1)", () => {
  it("opens an empty composer scoped to the domain WITHOUT auto-asking", () => {
    wrap(<ScopedAgentDock />);
    fireEvent.click(screen.getByLabelText("Gider Agent"));
    // No auto-submit / auto-answer on open.
    expect(streamCalls).toHaveLength(0);
    expect(screen.getByPlaceholderText("Gider Agent'a sorun…")).toBeInTheDocument();
    expect(screen.getByText("Örnek sorular:")).toBeInTheDocument();
  });

  it("submitting a typed question streams scoped to the domain", () => {
    wrap(<ScopedAgentDock />);
    fireEvent.click(screen.getByLabelText("Finans Agent"));
    fireEvent.change(screen.getByPlaceholderText("Finans Agent'a sorun…"), { target: { value: "nakit?" } });
    fireEvent.click(screen.getByLabelText("Gönder"));
    expect(streamCalls).toHaveLength(1);
    expect(streamCalls[0].body.scope).toBe("finans");
    expect(streamCalls[0].body.messages[0].content).toBe("nakit?");
  });

  it("clicking a suggestion chip asks scoped (explicit user action)", () => {
    wrap(<ScopedAgentDock />);
    fireEvent.click(screen.getByLabelText("Gider Agent"));
    fireEvent.click(screen.getByText("Hangi tedarikçiye en çok ödedim?"));
    expect(streamCalls).toHaveLength(1);
    expect(streamCalls[0].body.scope).toBe("gider");
  });
});

describe("ProposedActionCard (CR-011-D)", () => {
  it("director approves -> posts to the approvals flow + confirms", async () => {
    wrap(
      <ProposedActionCard
        action={{ request_id: "r9", kind: "agent_task", kind_label: "Görev (AI önerisi)", description: "Teklif hazırla", status: "pending", deep_link: "/approvals" }}
      />
    );
    fireEvent.click(screen.getByText("Onayla"));
    await waitFor(() => expect(apiPut).toHaveBeenCalledWith("/approvals/request/r9/approve", {}));
    expect(await screen.findByText(/Onaylandı ve uygulandı/)).toBeInTheDocument();
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("non-directors see a link to the approvals page, not Onayla", () => {
    mockAuth.user = { role: "project_manager" };
    wrap(
      <ProposedActionCard
        action={{ request_id: "r9", kind: "agent_task", kind_label: "Görev (AI önerisi)", description: "Teklif hazırla", status: "pending", deep_link: "/approvals" }}
      />
    );
    expect(screen.queryByText("Onayla")).not.toBeInTheDocument();
    expect(screen.getByText("Onaylar sayfası")).toBeInTheDocument();
  });
});

describe("YapiAIRail unified to the cited agent (CR-011-D)", () => {
  it("asks via the cited agent and shows citations + the trust badge", () => {
    wrap(<YapiAIRail onGoToTasks={() => {}} />);
    // New trust copy (no stale 'salt-okunur').
    expect(screen.getAllByText("Önerir, siz onaylarsınız").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByPlaceholderText("Yapı AI'ya bir şey sorun…"), { target: { value: "merhaba" } });
    fireEvent.click(screen.getByLabelText("Gönder"));
    expect(streamCalls).toHaveLength(1);

    act(() =>
      streamCalls[0].cb.onFinal({
        answer_markdown: "Yanıt hazır.",
        charts: [],
        citations: [{ type: "x", id: "1", label: "Kaynak A", deep_link: "/a" }],
        tools_used: [],
        generated_at: "2026-06-19T08:00:00Z",
        proposed_actions: [],
      })
    );
    expect(screen.getByText("Kaynak A")).toBeInTheDocument();
  });
});
