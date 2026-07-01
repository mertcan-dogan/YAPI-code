import { downloadFromUrl } from "@/lib/download";
import type { ProposedAction } from "@/types/agent";
import { Download, FileSpreadsheet, FileText } from "lucide-react";

// CR-044 — the run-result download card. When a skill runs (via the agent's
// run_skill tool in chat, or "Çalıştır" elsewhere), the agent emits a `run_result`
// "proposed action" — but it is NOT a proposal/approval. It is a compact, inline
// download card: the generated file's name + a format icon + an "İndir" button
// (the short-lived signed URL) and the "Oturum Çıktıları'na kaydedildi" caption.
// The figures come from the engine at run time; the LLM never writes them.
export function SkillRunCard({ action }: { action: ProposedAction }) {
  const format = action.format ?? "xlsx";
  const fileName = action.file_name ?? "rapor";
  const url = action.download_url ?? "";

  return (
    <div className="mt-3 flex items-center gap-3 rounded-control border border-border bg-surface p-3">
      <span
        className={
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-control " +
          (format === "pdf" ? "bg-red-50 text-danger" : "bg-green-50 text-success")
        }
      >
        {format === "pdf" ? <FileText className="h-5 w-5" /> : <FileSpreadsheet className="h-5 w-5" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-semibold text-text-primary">{fileName}</p>
        <p className="text-[11px] text-text-faint">Oturum Çıktıları'na kaydedildi</p>
      </div>
      <button
        type="button"
        onClick={() => url && downloadFromUrl(url, fileName)}
        disabled={!url}
        className="focus-ring inline-flex shrink-0 items-center gap-1 rounded-control bg-brand px-3 py-1.5 text-xs font-medium text-white transition hover:bg-brand/90 disabled:opacity-50"
      >
        <Download className="h-3.5 w-3.5" /> İndir
      </button>
    </div>
  );
}
