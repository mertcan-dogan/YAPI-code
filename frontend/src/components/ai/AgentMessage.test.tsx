// CR-038 §7-A — the shared <AgentMessage> renderer (AgentSteps + AgentAnswerBody
// + optional trust pill). The page-only extras (pin / disclaimer / generated-at
// line / trust badge) are default-off so the dashboard drawer/rail are unchanged.
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import type { AgentResponse } from "@/types/agent";

vi.mock("@/components/MarkdownText", () => ({
  MarkdownText: ({ text }: { text: string }) => createElement("div", null, text),
}));
vi.mock("@/components/charts/AgentChart", () => ({ AgentChart: () => createElement("div", { "data-testid": "chart" }) }));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: () => Promise.resolve({ data: { session: null } }) } },
}));
vi.mock("@/lib/api", () => ({
  api: { post: vi.fn() },
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  studio: { catalog: vi.fn(() => Promise.resolve({ metrics: [], dimensions: [] })), run: vi.fn(() => Promise.resolve({})) },
  baseURL: "",
}));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }));
vi.mock("@/store/auth", () => ({ useAuth: () => ({ user: { role: "director" } }) }));

import { AgentMessage } from "./AgentMessage";

const FINAL: AgentResponse = {
  answer_markdown: "Test yanıtı hazır.",
  charts: [],
  citations: [],
  tools_used: ["get_x"],
  generated_at: "2026-06-19T08:00:00Z",
  row_counts: { get_x: 2 },
  query_log_id: null,
  proposed_actions: [],
};

const base = {
  res: FINAL,
  liveText: "",
  streaming: false,
  step: "",
  error: false,
  question: "soru?",
  onNavigate: () => {},
};

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("AgentMessage (CR-038 shared renderer)", () => {
  it("passes res through to AgentAnswerBody (renders the answer)", () => {
    wrap(<AgentMessage {...base} />);
    expect(screen.getByText("Test yanıtı hazır.")).toBeInTheDocument();
  });

  it("renders no step panel when steps are empty", () => {
    wrap(<AgentMessage {...base} steps={[]} />);
    expect(screen.queryByText(/adım tamamlandı/)).not.toBeInTheDocument();
    expect(screen.queryByText("İşlem adımları")).not.toBeInTheDocument();
  });

  it("renders a collapsed step group when steps are present", () => {
    wrap(<AgentMessage {...base} steps={[{ label: "Adım", tool: "get_x" }]} />);
    expect(screen.getByText("1 adım tamamlandı")).toBeInTheDocument();
  });

  it("hides the trust badge by default and shows it when asked", () => {
    const { rerender } = wrap(<AgentMessage {...base} />);
    expect(screen.queryByText("Önerir, siz onaylarsınız")).not.toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <AgentMessage {...base} showTrustBadge />
      </MemoryRouter>
    );
    expect(screen.getByText("Önerir, siz onaylarsınız")).toBeInTheDocument();
  });

  it("shows the pin action only when onPin is provided", () => {
    const { rerender } = wrap(<AgentMessage {...base} />);
    expect(screen.queryByText("Sabitle")).not.toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <AgentMessage {...base} onPin={() => {}} />
      </MemoryRouter>
    );
    expect(screen.getByText("Sabitle")).toBeInTheDocument();
  });

  it("shows the standalone generated-at line only when enabled", () => {
    const { rerender } = wrap(<AgentMessage {...base} />);
    expect(screen.queryByText(/itibarıyla hesaplanmıştır/)).not.toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <AgentMessage {...base} showGeneratedAtLine />
      </MemoryRouter>
    );
    expect(screen.getByText(/itibarıyla hesaplanmıştır/)).toBeInTheDocument();
  });

  it("renders the graceful error message on error", () => {
    wrap(<AgentMessage {...base} res={null} error />);
    expect(screen.getByText(/Yapay zeka şu an kullanılamıyor/)).toBeInTheDocument();
  });
});
