// CR-044 — Uygulamalar (Beceriler / Skills) list. Mirrors StudioDashboardsPage.test:
// tabs Becerilerim / Tüm beceriler, debounced ?q= search, the format + görünürlük
// chips, son çalıştırma, the Çalıştır action (runSkill → download + toast), the row
// "…" menu (Düzenle / Sil — gated to owner or director), the delete confirm, the
// edit modal (updateSkill), and the empty + error+retry states. api/auth/toast/
// router/download mocked; DataTable + Menu render for real.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({
  user: { id: "me", role: "project_manager", full_name: "Ben" } as { id: string; role: string; full_name: string },
  skillsList: [
    { id: "s1", name: "Aylık Gelir-Gider", format: "xlsx", visibility: "private", owner_id: "me", updated_at: "2026-06-20T10:00:00Z", labels: null, last_run_at: "2026-06-25T09:00:00Z", last_run: { run_id: "r1", run_at: "2026-06-25T09:00:00Z", file_name: "aylik.xlsx", status: "ok" } },
    { id: "s2", name: "Çeyreklik PDF Raporu", format: "pdf", visibility: "company", owner_id: "other", updated_at: "2026-06-19T10:00:00Z", labels: null, last_run_at: null, last_run: null },
  ] as any[],
  full: { id: "s1", name: "Aylık Gelir-Gider", instruction: "Her ay özet.", plan: { format: "xlsx", title: "Aylık", widgets: [] }, format: "xlsx", visibility: "private", labels: null, owner_id: "me", created_by: "me", created_at: "2026-06-20T10:00:00Z", updated_at: "2026-06-20T10:00:00Z", is_owner: true, last_run: null } as any,
  runResult: { run_id: "r1", file_name: "aylik.xlsx", format: "xlsx", download_url: "https://signed/aylik.xlsx" } as any,
  runs: [
    { id: "r1", skill_id: "s1", status: "ok", file_name: "aylik.xlsx", format: "xlsx", run_at: "2026-06-25T09:00:00Z", error: null, run_by: "me" },
    { id: "r0", skill_id: "s1", status: "error", file_name: null, format: "xlsx", run_at: "2026-06-24T09:00:00Z", error: "Veri yok", run_by: "me" },
  ] as any[],
  downloadResult: { download_url: "https://signed/redl.xlsx", file_name: "aylik.xlsx", format: "xlsx" } as any,
  listMode: "ok" as "ok" | "fail",
  downloaded: [] as { url: string; name?: string }[],
}));

vi.mock("@/lib/api", () => ({
  skills: {
    listSkills: vi.fn(() => (h.listMode === "fail" ? Promise.reject(new Error("boom")) : Promise.resolve(h.skillsList))),
    runSkill: vi.fn(() => Promise.resolve(h.runResult)),
    getSkill: vi.fn(() => Promise.resolve(h.full)),
    updateSkill: vi.fn(() => Promise.resolve(h.full)),
    deleteSkill: vi.fn(() => Promise.resolve({ ok: true })),
    listSkillRuns: vi.fn(() => Promise.resolve(h.runs)),
    downloadSkillFile: vi.fn(() => Promise.resolve(h.downloadResult)),
  },
}));
vi.mock("@/lib/download", () => ({
  downloadFromUrl: vi.fn((url: string, name?: string) => h.downloaded.push({ url, name })),
}));
vi.mock("@/store/auth", () => ({ useAuth: (sel: any) => sel({ user: h.user }) }));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/layout/AppLayout", () => ({
  PageHeader: ({ title, action }: { title: string; action?: any }) => createElement("div", null, createElement("h1", null, title), action),
}));
const navigate = vi.fn();
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));

import { skills } from "@/lib/api";
import { downloadFromUrl } from "@/lib/download";
import { toast } from "@/store/toast";
import SkillsPage from "./SkillsPage";

beforeEach(() => {
  h.user = { id: "me", role: "project_manager", full_name: "Ben" };
  h.listMode = "ok";
  h.downloaded = [];
  h.skillsList = [
    { id: "s1", name: "Aylık Gelir-Gider", format: "xlsx", visibility: "private", owner_id: "me", updated_at: "2026-06-20T10:00:00Z", labels: null, last_run_at: "2026-06-25T09:00:00Z", last_run: { run_id: "r1", run_at: "2026-06-25T09:00:00Z", file_name: "aylik.xlsx", status: "ok" } },
    { id: "s2", name: "Çeyreklik PDF Raporu", format: "pdf", visibility: "company", owner_id: "other", updated_at: "2026-06-19T10:00:00Z", labels: null, last_run_at: null, last_run: null },
  ];
  navigate.mockClear();
  vi.clearAllMocks();
});
afterEach(cleanup);

it("Becerilerim shows only my skills; Tüm beceriler reveals the company one", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");
  expect(screen.queryByText("Çeyreklik PDF Raporu")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("Tüm beceriler"));
  expect(await screen.findByText("Çeyreklik PDF Raporu")).toBeInTheDocument();
});

it("renders a format badge (Excel/PDF), a görünürlük chip, and son çalıştırma", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");
  expect(screen.getByText("Excel")).toBeInTheDocument();
  expect(screen.getByText("Özel")).toBeInTheDocument();

  fireEvent.click(screen.getByText("Tüm beceriler"));
  const row = (await screen.findByText("Çeyreklik PDF Raporu")).closest("tr") as HTMLElement;
  expect(within(row).getByText("PDF")).toBeInTheDocument();
  expect(within(row).getByText("Herkes")).toBeInTheDocument();
  // A never-run skill shows the explicit "Henüz çalıştırılmadı" copy, never a blank.
  expect(within(row).getByText("Henüz çalıştırılmadı")).toBeInTheDocument();
});

it("Çalıştır runs the skill, downloads via the signed URL, and toasts where the file went + an İndir action", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");

  fireEvent.click(screen.getByLabelText("Çalıştır: Aylık Gelir-Gider"));
  await waitFor(() => expect(skills.runSkill).toHaveBeenCalledWith("s1"));
  await waitFor(() => expect(downloadFromUrl).toHaveBeenCalledWith("https://signed/aylik.xlsx", "aylik.xlsx"));
  // CR-044.1 — explicit "indirildi (İndirilenler klasörü)" + an İndir toast action.
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith(
      "Excel üretildi ve indirildi — İndirilenler klasörü",
      expect.objectContaining({ action: expect.objectContaining({ label: "İndir" }) })
    )
  );
});

it("shows a persistent per-row İndir that re-downloads the latest file via a fresh signed URL", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");

  // s1 has a last_run → its row shows İndir.
  fireEvent.click(screen.getByLabelText("İndir: Aylık Gelir-Gider"));
  await waitFor(() => expect(skills.downloadSkillFile).toHaveBeenCalledWith("r1"));
  await waitFor(() => expect(downloadFromUrl).toHaveBeenCalledWith("https://signed/redl.xlsx", "aylik.xlsx"));
});

it("a never-run skill shows no per-row İndir", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");
  fireEvent.click(screen.getByText("Tüm beceriler"));
  await screen.findByText("Çeyreklik PDF Raporu");
  expect(screen.queryByLabelText("İndir: Çeyreklik PDF Raporu")).not.toBeInTheDocument();
});

it("Çalıştırma geçmişi lists runs with an İndir per successful run", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");

  fireEvent.click(screen.getByLabelText("Beceri işlemleri: Aylık Gelir-Gider"));
  fireEvent.click(screen.getByText("Çalıştırma geçmişi"));
  await waitFor(() => expect(skills.listSkillRuns).toHaveBeenCalledWith("s1"));

  // The ok run is downloadable; the error run shows its status + reason, no İndir.
  expect(await screen.findByText("Başarılı")).toBeInTheDocument();
  expect(screen.getByText("Hata")).toBeInTheDocument();
  expect(screen.getByText("Veri yok")).toBeInTheDocument();

  // The modal's İndir has the exact accessible name "İndir" (the per-row button uses
  // an aria-label "İndir: …"), so this targets the modal's ok-run download.
  fireEvent.click(screen.getByRole("button", { name: "İndir" }));
  await waitFor(() => expect(skills.downloadSkillFile).toHaveBeenCalledWith("r1"));
});

it("surfaces a Türkçe error toast (not a silent failure) when a run fails", async () => {
  (skills.runSkill as any).mockRejectedValueOnce(new Error("patladı"));
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");

  fireEvent.click(screen.getByLabelText("Çalıştır: Aylık Gelir-Gider"));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("patladı"));
  expect(downloadFromUrl).not.toHaveBeenCalled();
});

it("hides Düzenle/Sil from a non-owner non-director", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");
  fireEvent.click(screen.getByText("Tüm beceriler"));
  await screen.findByText("Çeyreklik PDF Raporu");

  fireEvent.click(screen.getByLabelText("Beceri işlemleri: Çeyreklik PDF Raporu"));
  expect(screen.queryByText("Düzenle")).not.toBeInTheDocument();
  expect(screen.queryByText("Sil")).not.toBeInTheDocument();
});

it("shows Düzenle + Sil to the owner of a skill", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");
  fireEvent.click(screen.getByLabelText("Beceri işlemleri: Aylık Gelir-Gider"));
  expect(screen.getByText("Düzenle")).toBeInTheDocument();
  expect(screen.getByText("Sil")).toBeInTheDocument();
});

it("Sil deletes only after a confirm", async () => {
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");

  fireEvent.click(screen.getByLabelText("Beceri işlemleri: Aylık Gelir-Gider"));
  fireEvent.click(screen.getByText("Sil"));
  expect(confirmSpy).toHaveBeenCalled();
  expect(skills.deleteSkill).not.toHaveBeenCalled();

  confirmSpy.mockReturnValue(true);
  fireEvent.click(screen.getByLabelText("Beceri işlemleri: Aylık Gelir-Gider"));
  fireEvent.click(screen.getByText("Sil"));
  await waitFor(() => expect(skills.deleteSkill).toHaveBeenCalledWith("s1"));
  confirmSpy.mockRestore();
});

it("Düzenle opens the edit modal and saves via updateSkill", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");

  fireEvent.click(screen.getByLabelText("Beceri işlemleri: Aylık Gelir-Gider"));
  fireEvent.click(screen.getByText("Düzenle"));
  await waitFor(() => expect(skills.getSkill).toHaveBeenCalledWith("s1"));

  // The modal prefills the name; edit it and Kaydet → updateSkill.
  const nameInput = (await screen.findByLabelText("Beceri adı")) as HTMLInputElement;
  expect(nameInput.value).toBe("Aylık Gelir-Gider");
  fireEvent.change(nameInput, { target: { value: "Yeni ad" } });
  fireEvent.click(screen.getByText("Kaydet"));

  await waitFor(() =>
    expect(skills.updateSkill).toHaveBeenCalledWith("s1", expect.objectContaining({ name: "Yeni ad" }))
  );
});

it("debounced search hits the server-side ?q= filter", async () => {
  render(<SkillsPage />);
  await screen.findByText("Aylık Gelir-Gider");
  expect(skills.listSkills).toHaveBeenCalledWith(undefined);

  fireEvent.change(screen.getByLabelText("Beceri ara"), { target: { value: "gelir" } });
  await waitFor(() => expect(skills.listSkills).toHaveBeenCalledWith("gelir"));
});

it("shows the friendly empty state when there are no skills", async () => {
  h.skillsList = [];
  render(<SkillsPage />);
  expect(
    await screen.findByText("Henüz beceri yok — Yapı AI ile sohbette bir beceri oluşturun.")
  ).toBeInTheDocument();
});

it("shows an error + retry (never reads as empty) and recovers on retry", async () => {
  h.listMode = "fail";
  render(<SkillsPage />);
  const retry = await screen.findByText("Tekrar Dene");
  expect(retry).toBeInTheDocument();

  h.listMode = "ok";
  fireEvent.click(retry);
  expect(await screen.findByText("Aylık Gelir-Gider")).toBeInTheDocument();
});
