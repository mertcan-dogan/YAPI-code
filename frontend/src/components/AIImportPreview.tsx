import { Button } from "@/components/ui";
import { COST_CATEGORIES } from "@/constants";
import { api, apiPost } from "@/lib/api";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import { formatCurrency, toNumber } from "@/utils/format";
import { Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

const TABS = [
  { key: "maliyet_girisleri", label: "Maliyet Girişleri" },
  { key: "faturalar", label: "Faturalar & Hakediş" },
  { key: "alt_yukleniciler", label: "Alt Yükleniciler" },
  { key: "ekipman", label: "Ekipman" },
  { key: "tanimsiz", label: "Tanımlanamayan" },
] as const;

type Extracted = Record<string, any[]>;

function ConfidenceDot({ c }: { c: number }) {
  const color = c > 0.85 ? "#10B981" : c >= 0.6 ? "#EAB308" : "#EF4444";
  const label = c > 0.85 ? "Yüksek güven" : c >= 0.6 ? "Orta güven — kontrol edin" : "Düşük güven — düzenleme gerekli";
  return (
    <span className="inline-flex items-center gap-1 text-xs" title={label}>
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}

// CR-002-H: AI Excel import — tabbed structured preview.
export function AIImportPreview({ projectId, file, onClose, onDone }: { projectId: string; file: File; onClose: () => void; onDone: () => void }) {
  const [loading, setLoading] = useState(true);
  const [extracted, setExtracted] = useState<Extracted>({});
  const [analysis, setAnalysis] = useState<any>(null);
  const [tab, setTab] = useState<string>("maliyet_girisleri");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const fd = new FormData();
    fd.append("file", file);
    api
      .post(`/projects/${projectId}/ai-import`, fd)
      .then((res) => {
        setExtracted(res.data.data.extracted_data ?? {});
        setAnalysis(res.data.data.analysis ?? null);
      })
      .catch((e) => {
        toast.error(e.message ?? "AI şu an kullanılamıyor. Standart içe aktarma kullanın.");
        onClose();
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, projectId]);

  const confirm = async (highOnly: boolean) => {
    setSaving(true);
    try {
      const pick = (rows: any[] = []) =>
        rows.filter((r) => !highOnly || toNumber(r.confidence) > 0.85).map(({ confidence, ...rest }) => rest);
      const body = {
        maliyet_girisleri: pick(extracted.maliyet_girisleri),
        faturalar: pick(extracted.faturalar),
        alt_yukleniciler: pick(extracted.alt_yukleniciler),
        ekipman: pick(extracted.ekipman),
      };
      const res = await apiPost<{ imported: any; skipped: number }>(`/projects/${projectId}/ai-import/confirm`, body);
      const i = res.imported;
      toast.success(`İçe aktarıldı — Maliyet: ${i.maliyet_girisleri}, Fatura: ${i.faturalar}, Alt Yük.: ${i.alt_yukleniciler}, Ekipman: ${i.ekipman}`);
      onDone();
    } catch (e: any) {
      toast.error(e.message ?? "İçe aktarma başarısız");
    } finally {
      setSaving(false);
    }
  };

  const rows: any[] = extracted[tab] ?? [];

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-bg">
      <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
        <h2 className="flex items-center gap-2 text-lg font-bold text-primary">
          <Sparkles className="h-5 w-5 text-accent" /> AI ile İçe Aktarma
        </h2>
        <button onClick={onClose} className="text-text-secondary hover:text-text-primary"><X className="h-5 w-5" /></button>
      </div>

      {loading ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-text-secondary">
          <Sparkles className="h-8 w-8 animate-pulse text-accent" />
          AI dosyanızı analiz ediyor... (genellikle 10-30 saniye)
        </div>
      ) : (
        <>
          <div className="flex gap-1 border-b border-border bg-surface px-6">
            {TABS.map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)} className={cn("border-b-2 px-3 py-2 text-sm", tab === t.key ? "border-primary font-semibold text-primary" : "border-transparent text-text-secondary")}>
                {t.label} ({(extracted[t.key] ?? []).length})
              </button>
            ))}
          </div>

          {analysis?.truncated && (
            <div className="bg-amber-50 px-6 py-2 text-xs text-text-primary">Dosyanızın ilk 500 satırı işlendi. Kalan veriler için tekrar yükleyin.</div>
          )}

          <div className="flex-1 overflow-auto p-6">
            {rows.length === 0 ? (
              <p className="text-sm text-text-secondary">Bu kategoride kayıt bulunamadı.</p>
            ) : (
              <div className="space-y-2">
                {rows.map((r, i) => (
                  <div key={i} className={cn("rounded-md border bg-surface p-3", tab === "tanimsiz" && "bg-amber-50")}>
                    <div className="mb-1 flex items-center justify-between">
                      <ConfidenceDot c={toNumber(r.confidence)} />
                    </div>
                    <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm md:grid-cols-3">
                      {Object.entries(r).filter(([k]) => k !== "confidence").map(([k, v]) => (
                        <div key={k} className="truncate">
                          <span className="text-text-secondary">{k === "cost_category" ? "kategori" : k}: </span>
                          <span className="font-medium">
                            {k === "cost_category" ? (COST_CATEGORIES[String(v)] ?? String(v)) : k.includes("amount") || k.includes("value") || k.includes("rate") ? formatCurrency(v as any) : String(v ?? "—")}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-border bg-surface px-6 py-3">
            <Button variant="ghost" onClick={onClose}>İptal</Button>
            <Button variant="outline" loading={saving} onClick={() => confirm(true)}>Yalnızca Yüksek Güvenlileri Aktar</Button>
            <Button loading={saving} onClick={() => confirm(false)}>Tümünü Onayla ve İçe Aktar</Button>
          </div>
        </>
      )}
    </div>
  );
}
