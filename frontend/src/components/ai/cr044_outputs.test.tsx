// CR-044 — the run-result download card (SkillRunCard) + the SessionOutputsPanel
// "Üretilen dosyalar" list. Both render a generated file (name + format icon) and
// an İndir that downloads via the signed download_url. download mocked.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createElement } from "react";

const h = vi.hoisted(() => ({ downloaded: [] as { url: string; name?: string }[] }));
vi.mock("@/lib/download", () => ({
  downloadFromUrl: vi.fn((url: string, name?: string) => h.downloaded.push({ url, name })),
}));
// AgentChart pulls recharts; the panel only needs it for the (absent) Tuval chart.
vi.mock("@/components/charts/AgentChart", () => ({ AgentChart: () => createElement("div", { "data-testid": "chart" }) }));

import { downloadFromUrl } from "@/lib/download";
import { SkillRunCard } from "./SkillRunCard";
import { SessionOutputsPanel } from "./SessionOutputsPanel";

const RUN_ACTION: any = {
  kind: "run_result", kind_label: "Üretilen Dosya",
  file_name: "dgn-marti-haziran.xlsx", format: "xlsx",
  download_url: "https://signed/dgn.xlsx", run_id: "run-1", skill_id: "s1", skill_name: "DGN Özeti",
};

beforeEach(() => {
  h.downloaded = [];
  vi.clearAllMocks();
});
afterEach(cleanup);

it("SkillRunCard shows the file name + the session-outputs caption and downloads via the signed URL", () => {
  render(<SkillRunCard action={RUN_ACTION} />);
  expect(screen.getByText("dgn-marti-haziran.xlsx")).toBeInTheDocument();
  expect(screen.getByText("Oturum Çıktıları'na kaydedildi")).toBeInTheDocument();

  fireEvent.click(screen.getByText("İndir"));
  expect(downloadFromUrl).toHaveBeenCalledWith("https://signed/dgn.xlsx", "dgn-marti-haziran.xlsx");
});

it("SessionOutputsPanel lists this session's generated files with İndir per file", () => {
  render(
    <SessionOutputsPanel
      latestChart={null}
      canPin={false}
      onPin={() => {}}
      onViewWorkspace={() => {}}
      projectId=""
      onProjectChange={() => {}}
      projects={[]}
      skillRuns={[
        { run_id: "run-1", file_name: "dgn.xlsx", format: "xlsx", download_url: "https://signed/dgn.xlsx" },
        { run_id: "run-2", file_name: "ceyrek.pdf", format: "pdf", download_url: "https://signed/ceyrek.pdf" },
      ]}
    />
  );
  expect(screen.getByText("Üretilen dosyalar")).toBeInTheDocument();
  expect(screen.getByText("dgn.xlsx")).toBeInTheDocument();
  expect(screen.getByText("ceyrek.pdf")).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText("İndir: ceyrek.pdf"));
  expect(downloadFromUrl).toHaveBeenCalledWith("https://signed/ceyrek.pdf", "ceyrek.pdf");
});

it("SessionOutputsPanel shows an empty state when no files were generated", () => {
  render(
    <SessionOutputsPanel
      latestChart={null}
      canPin={false}
      onPin={() => {}}
      onViewWorkspace={() => {}}
      projectId=""
      onProjectChange={() => {}}
      projects={[]}
      skillRuns={[]}
    />
  );
  const section = screen.getByText("Üretilen dosyalar").parentElement as HTMLElement;
  expect(
    within(section).getByText("Bir beceri çalıştırdığınızda üretilen dosyalar burada listelenir.")
  ).toBeInTheDocument();
});
