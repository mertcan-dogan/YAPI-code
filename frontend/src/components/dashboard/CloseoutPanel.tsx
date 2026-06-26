import { Badge, Button, Input, Label, Modal, Skeleton } from "@/components/ui";
import { LoadError } from "@/components/EmptyState";
import { useFetch } from "@/hooks/useFetch";
import { api, apiPost } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { CloseoutObj, CloseoutResponse, CloseoutStage, CloseoutSummary } from "@/types";
import { formatDate, formatDateTime } from "@/utils/format";
import { CheckCircle2, ChevronRight, Download, Flag, History, Lock, RotateCcw } from "lucide-react";
import { Fragment, useState } from "react";

const STAGE_ORDER: CloseoutStage[] = ["gecici_kabul", "kesin_hesap", "kesin_kabul"];
const STAGE_LABELS: Record<CloseoutStage, string> = {
  gecici_kabul: "Geçici Kabul",
  kesin_hesap: "Kesin Hesap",
  kesin_kabul: "Kesin Kabul",
};
// URL slug per stage POST action.
const STAGE_SLUG: Record<CloseoutStage, string> = {
  gecici_kabul: "gecici-kabul",
  kesin_hesap: "kesin-hesap",
  kesin_kabul: "kesin-kabul",
};
const STAGE_DATE_KEY: Record<CloseoutStage, "gecici_kabul_date" | "kesin_hesap_date" | "kesin_kabul_date"> = {
  gecici_kabul: "gecici_kabul_date",
  kesin_hesap: "kesin_hesap_date",
  kesin_kabul: "kesin_kabul_date",
};

const today = () => new Date().toISOString().slice(0, 10);

function stageDate(co: CloseoutObj | null | undefined, st: CloseoutStage): string | null {
  return co ? (co[STAGE_DATE_KEY[st]] as string | null) : null;
}

// Horizontal stage timeline: Geçici Kabul → Kesin Hesap → Kesin Kabul. A stage is
// "done" once its acceptance date is set; connectors fill as stages complete.
function CloseoutTimeline({ closeout, compact }: { closeout: CloseoutObj | null | undefined; compact?: boolean }) {
  return (
    <div className="flex items-start">
      {STAGE_ORDER.map((st, i) => {
        const date = stageDate(closeout, st);
        const done = !!date;
        const prevDone = i > 0 && !!stageDate(closeout, STAGE_ORDER[i - 1]);
        return (
          <Fragment key={st}>
            {i > 0 && <div className={cn("mt-3 h-0.5 flex-1", prevDone ? "bg-success" : "bg-border")} />}
            <div className="flex shrink-0 flex-col items-center px-1 text-center">
              <span
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-full border-2",
                  done ? "border-success bg-success text-white" : "border-border bg-surface text-text-disabled"
                )}
              >
                {done ? <CheckCircle2 className="h-4 w-4" /> : <span className="text-[11px] font-semibold">{i + 1}</span>}
              </span>
              <span className={cn("mt-1 text-xs font-medium", done ? "text-primary" : "text-text-secondary")}>{STAGE_LABELS[st]}</span>
              {!compact && <span className="tabular text-[11px] text-text-secondary">{date ? formatDate(date) : "—"}</span>}
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}

// Pre-formatted Turkish summary figures shown once the report is frozen.
function SummaryGrid({ summary }: { summary: CloseoutSummary }) {
  const rows: { label: string; value: string }[] = [
    { label: "Sözleşme Değeri", value: summary.contract_value },
    { label: "Gerçekleşen Maliyet", value: summary.total_actual },
    { label: "Tahmini Final", value: summary.forecast_final },
    { label: "Kar Marjı", value: summary.margin_pct },
    { label: "Net Nakit", value: summary.net_cash },
    { label: "Rapor Tarihi", value: summary.report_date },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {rows.map((r) => (
        <div key={r.label}>
          <div className="text-[11px] text-text-secondary">{r.label}</div>
          <div className="tabular font-semibold text-primary">{r.value}</div>
        </div>
      ))}
    </div>
  );
}

export function CloseoutPanel({ projectId, isDirector }: { projectId: string; isDirector: boolean }) {
  const { data, loading, error, refetch } = useFetch<CloseoutResponse>(`/projects/${projectId}/closeout`);
  // PDF export is gated to director/PM/finance — site managers get a 403 from both
  // report.pdf endpoints, so hide every PDF button for them.
  const isSiteManager = useAuth((s) => s.user?.role === "site_manager");

  const [advanceOpen, setAdvanceOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [date, setDate] = useState(today());
  const [busy, setBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  // Lazy archive — only fetched once "Kapanış Geçmişi" is expanded.
  const history = useFetch<CloseoutObj[]>(historyOpen ? `/projects/${projectId}/closeouts` : null);

  const closeout = data?.closeout ?? null;
  const completed = data?.project_status === "completed";
  const reachedIdx = closeout?.stage ? STAGE_ORDER.indexOf(closeout.stage) : -1;
  const nextStage: CloseoutStage | undefined = STAGE_ORDER[reachedIdx + 1];
  const stageLabel = closeout?.stage ? STAGE_LABELS[closeout.stage] : null;

  const runStage = async () => {
    if (!nextStage) return;
    setBusy(true);
    try {
      await apiPost(`/projects/${projectId}/closeout/${STAGE_SLUG[nextStage]}`, { date });
      toast.success(`${STAGE_LABELS[nextStage]} kaydedildi`);
      setAdvanceOpen(false);
      refetch();
      if (historyOpen) history.refetch();
    } catch (e: any) {
      toast.error(e?.message ?? "İşlem tamamlanamadı");
    } finally {
      setBusy(false);
    }
  };

  // Re-freeze the report (re-run Kesin Hesap) when the snapshot is stale.
  const refreeze = async () => {
    setBusy(true);
    try {
      await apiPost(`/projects/${projectId}/closeout/kesin-hesap`, { date: today() });
      toast.success("Rapor yeniden donduruldu");
      refetch();
      if (historyOpen) history.refetch();
    } catch (e: any) {
      toast.error(e?.message ?? "Rapor dondurulamadı");
    } finally {
      setBusy(false);
    }
  };

  const reopen = async () => {
    setBusy(true);
    try {
      await apiPost(`/projects/${projectId}/reopen`);
      toast.success("Proje yeniden açıldı");
      setReopenOpen(false);
      refetch();
      if (historyOpen) history.refetch();
    } catch (e: any) {
      toast.error(e?.message ?? "Proje yeniden açılamadı");
    } finally {
      setBusy(false);
    }
  };

  // No closeoutId → CURRENT active closeout report. With closeoutId → that specific
  // (possibly archived/reopened) record's own frozen snapshot.
  const downloadPdf = async (closeoutId?: string) => {
    const path = closeoutId
      ? `/projects/${projectId}/closeouts/${closeoutId}/report.pdf`
      : `/projects/${projectId}/closeout/report.pdf`;
    try {
      const res = await api.get(path, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "proje-sonu-raporu.pdf";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Rapor indirildi");
    } catch (e: any) {
      toast.error(e?.message ?? "Rapor indirilemedi");
    }
  };

  if (loading) {
    return (
      <div className="mt-4 rounded-xl border border-border bg-surface p-4 shadow-sm">
        <Skeleton className="mb-3 h-4 w-40" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="mt-4 rounded-xl border border-border bg-surface shadow-sm">
        <LoadError message="Proje kapanışı yüklenemedi." onRetry={refetch} />
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-xl border border-border bg-surface shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-primary">
          <Flag className="h-4 w-4 text-brand" /> Proje Kapanışı
        </span>
        <div className="flex items-center gap-2">
          <Badge variant={completed ? "success" : "info"}>{completed ? "Tamamlandı" : "Aktif"}</Badge>
          {stageLabel && <Badge variant="neutral">{stageLabel}</Badge>}
        </div>
      </div>

      <div className="space-y-4 p-4">
        <CloseoutTimeline closeout={closeout} />

        {/* Stale-report hint (subtle). */}
        {data?.report_stale && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-dashed border-accent bg-amber-50 px-3 py-2 text-xs text-text-secondary">
            <span>Rapor güncel değil — yeniden dondurabilirsiniz.</span>
            {isDirector && (
              <button onClick={refreeze} disabled={busy} className="font-medium text-brand hover:underline disabled:opacity-50">
                Yeniden Dondur
              </button>
            )}
          </div>
        )}

        {/* Frozen report → summary figures + PDF download (visible to everyone). */}
        {data?.report_frozen && data?.summary && (
          <div className="space-y-3 rounded-lg border border-border bg-bg p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-primary">
                <Lock className="h-3.5 w-3.5 text-success" /> Proje Sonu Raporu (donduruldu)
              </span>
              {!isSiteManager && (
                <Button variant="outline" className="px-2.5 py-1 text-xs" onClick={() => downloadPdf()}>
                  <Download className="h-3.5 w-3.5" /> Proje Sonu Raporu (PDF) indir
                </Button>
              )}
            </div>
            <SummaryGrid summary={data.summary} />
            <p className="text-[11px] italic text-text-disabled">Oluşturuldu: {formatDateTime(data.summary.generated_at)}</p>
          </div>
        )}

        {/* Director-only lifecycle actions. */}
        {isDirector && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
            {nextStage ? (
              <Button className="px-3 py-1.5 text-sm" onClick={() => { setDate(today()); setAdvanceOpen(true); }}>
                Sonraki Aşama: {STAGE_LABELS[nextStage]} <ChevronRight className="h-4 w-4" />
              </Button>
            ) : (
              <span className="text-xs text-text-secondary">Tüm kapanış aşamaları tamamlandı.</span>
            )}
            {(closeout?.stage || completed) && (
              <Button variant="ghost" className="px-3 py-1.5 text-sm" onClick={() => setReopenOpen(true)}>
                <RotateCcw className="h-4 w-4" /> Yeniden Aç
              </Button>
            )}
          </div>
        )}

        {/* Kapanış Geçmişi — archive incl. reopened history (lazy). */}
        <div className="border-t border-border pt-3">
          <button
            onClick={() => setHistoryOpen((v) => !v)}
            className="flex items-center gap-1.5 text-xs font-medium text-brand"
          >
            <History className="h-3.5 w-3.5" />
            <span className="inline-block w-3">{historyOpen ? "▾" : "▸"}</span>
            Kapanış Geçmişi
          </button>
          {historyOpen && (
            <div className="mt-3">
              {history.loading ? (
                <Skeleton className="h-12 w-full" />
              ) : history.error ? (
                <LoadError message="Kapanış geçmişi yüklenemedi." onRetry={history.refetch} />
              ) : (history.data?.length ?? 0) === 0 ? (
                <p className="text-xs text-text-secondary">Henüz kapanış kaydı yok.</p>
              ) : (
                <div className="space-y-3">
                  {history.data!.map((co) => (
                    <div key={co.id} className="rounded-lg border border-border p-3">
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <span className="flex items-center gap-2 text-xs">
                          {co.is_active ? <Badge variant="info">Güncel</Badge> : <Badge variant="neutral">Arşiv</Badge>}
                          {co.reopened_at && <span className="text-text-secondary">Yeniden açıldı: {formatDate(co.reopened_at)}</span>}
                        </span>
                        {co.report_frozen && co.frozen_at && (
                          <span className="flex items-center gap-1 text-[11px] text-text-secondary">
                            <Lock className="h-3 w-3 text-success" /> Donduruldu: {formatDateTime(co.frozen_at)}
                          </span>
                        )}
                      </div>
                      <CloseoutTimeline closeout={co} compact />
                      {co.report_frozen && !isSiteManager && (
                        <div className="mt-2">
                          <button onClick={() => downloadPdf(co.id)} className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
                            <Download className="h-3 w-3" /> PDF indir
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Advance-stage modal (director-only) with the acceptance date. */}
      <Modal open={advanceOpen} title={nextStage ? STAGE_LABELS[nextStage] : "Sonraki Aşama"} onClose={() => setAdvanceOpen(false)} size="md">
        <div className="space-y-3">
          <p className="text-sm text-text-secondary">
            {nextStage === "kesin_hesap"
              ? "Kesin hesap aşaması proje sonu raporunu dondurur. Kabul tarihini seçin."
              : "Kabul tarihini seçin."}
          </p>
          <div>
            <Label required>Kabul Tarihi</Label>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button variant="ghost" onClick={() => setAdvanceOpen(false)}>İptal</Button>
            <Button loading={busy} disabled={!date} onClick={runStage}>Onayla</Button>
          </div>
        </div>
      </Modal>

      {/* Reopen confirmation (director-only). */}
      <Modal open={reopenOpen} title="Projeyi Yeniden Aç" onClose={() => setReopenOpen(false)} size="md">
        <div className="space-y-3">
          <p className="text-sm text-text-secondary">
            Proje yeniden aktif duruma getirilecek ve mevcut kapanış arşive alınacaktır. Devam etmek istiyor musunuz?
          </p>
          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button variant="ghost" onClick={() => setReopenOpen(false)}>İptal</Button>
            <Button variant="danger" loading={busy} onClick={reopen}>Yeniden Aç</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
