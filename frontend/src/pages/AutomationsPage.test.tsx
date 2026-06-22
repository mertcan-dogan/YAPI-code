// CR-012-E smoke test for the Otomasyonlar page: both curated templates render
// as cards, the enable toggle persists via PUT /automations/{key}, and the
// config drawer opens. useFetch + api are mocked.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  list: {
    data: [
      {
        template_key: "document_auto_file",
        title: "Belge Otomatik Dosyalama",
        description: "Belge sınıflandırma açıklaması",
        kind: "event",
        id: null,
        enabled: false,
        config: { min_confidence: 0.75, destinations: ["cost", "client_invoice"] },
        last_run_at: null,
        next_run_at: null,
        last_run: null,
      },
      {
        template_key: "recurring_digest",
        title: "Periyodik Özet",
        description: "Periyodik özet açıklaması",
        kind: "scheduled",
        id: "a1",
        enabled: true,
        config: { cadence: "weekly", day_of_week: 0, hour: 8, delivery: { in_app: true, email: false } },
        last_run_at: "2026-06-20T05:00:00Z",
        next_run_at: "2026-06-27T05:00:00Z",
        last_run: { status: "success", summary: { notifications: 2, emails: 0 }, started_at: "2026-06-20T05:00:00Z" },
      },
    ] as any[],
    meta: null,
    loading: false,
    error: null as string | null,
    refetch: vi.fn(),
  },
}));

vi.mock("@/hooks/useFetch", () => ({ useFetch: () => h.list }));
vi.mock("@/lib/api", () => ({ apiPut: vi.fn(() => Promise.resolve({})) }));
vi.mock("@/store/auth", () => ({ useAuth: (sel: any) => sel({ user: { role: "director" } }) }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({ PageHeader: ({ title }: { title: string }) => createElement("h1", null, title) }));

import { apiPut } from "@/lib/api";
import AutomationsPage from "./AutomationsPage";

afterEach(cleanup);

it("renders both curated templates as cards", () => {
  render(<AutomationsPage />);
  expect(screen.getByText("Belge Otomatik Dosyalama")).toBeInTheDocument();
  expect(screen.getByText("Periyodik Özet")).toBeInTheDocument();
  // The scheduled template surfaces its next-run time.
  expect(screen.getByText(/Sonraki çalışma:/)).toBeInTheDocument();
});

it("toggling enable persists via PUT /automations/{key}", async () => {
  render(<AutomationsPage />);
  // The first switch belongs to document_auto_file (currently disabled).
  const toggles = screen.getAllByRole("switch");
  fireEvent.click(toggles[0]);
  await waitFor(() =>
    expect(apiPut).toHaveBeenCalledWith(
      "/automations/document_auto_file",
      expect.objectContaining({ enabled: true })
    )
  );
});

it("opens the config drawer via Yapılandır", () => {
  render(<AutomationsPage />);
  fireEvent.click(screen.getAllByText("Yapılandır")[1]); // recurring_digest
  expect(screen.getByText("Tekrar Aralığı")).toBeInTheDocument();
});
