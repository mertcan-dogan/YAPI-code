import { api } from "@/lib/api";
import { toast } from "@/store/toast";
import type { AgentResponse } from "@/types/agent";
import { ChevronDown, Download, FileSpreadsheet, FileText } from "lucide-react";
import { useState } from "react";

// CR-011-D §4.1 — export an agent answer (text + chart(s) + citations) to PDF or
// Excel via POST /ai/agent/export, reusing the backend reports renderer. Downloads
// the returned file blob.
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function AnalysisExportButton({ res, question }: { res: AgentResponse; question?: string | null }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const exportAs = async (fmt: "pdf" | "excel") => {
    setBusy(true);
    try {
      const resp = await api.post(
        "/ai/agent/export",
        {
          answer_markdown: res.answer_markdown,
          charts: res.charts ?? [],
          citations: res.citations ?? [],
          question: question ?? null,
          title: "Yapı AI Analizi",
        },
        { params: { fmt }, responseType: "blob" }
      );
      downloadBlob(resp.data, fmt === "excel" ? "yapi-ai-analiz.xlsx" : "yapi-ai-analiz.pdf");
    } catch {
      toast.error("Analiz dışa aktarılamadı");
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  return (
    <div className="relative mt-3 inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={busy}
        className="focus-ring inline-flex items-center gap-1.5 rounded-control border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text-primary transition hover:border-brand disabled:opacity-50"
      >
        <Download className="h-3.5 w-3.5" /> Dışa aktar
        <ChevronDown className="h-3 w-3 text-text-secondary" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-30 mt-1 w-40 overflow-hidden rounded-xl border border-border bg-surface py-1 shadow-lg">
            <button
              onClick={() => exportAs("pdf")}
              disabled={busy}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-text-primary hover:bg-navy-50 disabled:opacity-50"
            >
              <FileText className="h-3.5 w-3.5 text-brand" /> PDF
            </button>
            <button
              onClick={() => exportAs("excel")}
              disabled={busy}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-text-primary hover:bg-navy-50 disabled:opacity-50"
            >
              <FileSpreadsheet className="h-3.5 w-3.5 text-success" /> Excel (.xlsx)
            </button>
          </div>
        </>
      )}
    </div>
  );
}
