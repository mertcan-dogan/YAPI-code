import { Button, Input, Select } from "@/components/ui";
import { COST_CATEGORIES, COST_CATEGORY_OPTIONS } from "@/constants";
import { api, apiPost } from "@/lib/api";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import { formatCurrency, toNumber } from "@/utils/format";
import { Pencil, Plus, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

const TABS = [
  { key: "maliyet_girisleri", label: "Maliyet Girişleri" },
  { key: "faturalar", label: "Faturalar & Hakediş" },
  { key: "alt_yukleniciler", label: "Alt Yükleniciler" },
  { key: "ekipman", label: "Ekipman" },
  { key: "tanimsiz", label: "Tanımlanamayan" },
] as const;

type FieldType = "text" | "number" | "date" | "category" | "status" | "ownership" | "vat" | "unit";
interface Field {
  key: string;
  label: string;
  type: FieldType;
}

// CR-003-B: Turkish labels + field types per category.
const FIELDS: Record<string, Field[]> = {
  maliyet_girisleri: [
    { key: "entry_date", label: "Tarih", type: "date" },
    { key: "cost_category", label: "Kategori", type: "category" },
    { key: "supplier_name", label: "Tedarikçi", type: "text" },
    { key: "description", label: "Açıklama", type: "text" },
    { key: "amount_try", label: "Tutar (TRY)", type: "number" },
    { key: "vat_rate", label: "KDV Oranı", type: "vat" },
    { key: "payment_due_date", label: "Vade Tarihi", type: "date" },
    { key: "payment_status", label: "Ödeme Durumu", type: "status" },
  ],
  faturalar: [
    { key: "invoice_number", label: "Fatura No", type: "text" },
    { key: "invoice_date", label: "Fatura Tarihi", type: "date" },
    { key: "amount_try", label: "Tutar (TRY)", type: "number" },
    { key: "vat_rate", label: "KDV Oranı", type: "vat" },
    { key: "due_date", label: "Vade Tarihi", type: "date" },
  ],
  alt_yukleniciler: [
    { key: "name", label: "Ad", type: "text" },
    { key: "scope_of_work", label: "İş Kapsamı", type: "text" },
    { key: "contract_value_try", label: "Sözleşme Değeri", type: "number" },
  ],
  ekipman: [
    { key: "equipment_name", label: "Ekipman Adı", type: "text" },
    { key: "ownership_type", label: "Sahiplik", type: "ownership" },
    { key: "rate_try", label: "Birim Ücret", type: "number" },
    { key: "rate_unit", label: "Birim", type: "unit" },
    { key: "deployment_start", label: "Başlangıç Tarihi", type: "date" },
  ],
  tanimsiz: [{ key: "raw", label: "Veri", type: "text" }],
};

function ConfidenceChip({ c }: { c: number }) {
  const cfg = c > 0.85
    ? { bg: "#DCFCE7", fg: "#166534", dot: "#10B981", label: "Yüksek Güven" }
    : c >= 0.6
    ? { bg: "#FEF9C3", fg: "#854D0E", dot: "#EAB308", label: "Kontrol Edin" }
    : { bg: "#FEE2E2", fg: "#991B1B", dot: "#EF4444", label: "Düzenleme Gerekli" };
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium" style={{ backgroundColor: cfg.bg, color: cfg.fg }}>
      <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: cfg.dot }} /> {cfg.label}
    </span>
  );
}

function displayValue(f: Field, v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (f.type === "category") return COST_CATEGORIES[String(v)] ?? String(v);
  if (f.type === "status") return v === "paid" ? "Ödendi" : "Ödenmedi";
  if (f.type === "ownership") return v === "owned" ? "Şirkete Ait" : "Kiralık";
  if (f.type === "unit") return v === "month" ? "Ay" : "Gün";
  if (f.type === "number") return formatCurrency(v);
  return String(v);
}

export function AIImportPreview({ projectId, file, onClose, onDone }: { projectId: string; file: File; onClose: () => void; onDone: () => void }) {
  const [loading, setLoading] = useState(true);
  const [extracted, setExtracted] = useState<Record<string, any[]>>({});
  const [analysis, setAnalysis] = useState<any>(null);
  const [tab, setTab] = useState<string>("maliyet_girisleri");
  const [editingRow, setEditingRow] = useState<number | null>(null);
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

  const rows: any[] = extracted[tab] ?? [];
  const fields = FIELDS[tab] ?? [];

  const setRows = (next: any[]) => setExtracted((e) => ({ ...e, [tab]: next }));
  const updateRow = (i: number, key: string, value: any) => setRows(rows.map((r, j) => (j === i ? { ...r, [key]: value } : r)));
  const deleteRow = (i: number) => setRows(rows.filter((_, j) => j !== i));
  const addRow = () => { const blank: any = { confidence: 1 }; fields.forEach((f) => (blank[f.key] = "")); setRows([...rows, blank]); setEditingRow(rows.length); };

  const confirm = async (highOnly: boolean) => {
    setSaving(true);
    try {
      const pick = (list: any[] = []) => list.filter((r) => !highOnly || toNumber(r.confidence) > 0.85).map(({ confidence, ...rest }) => rest);
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

  function renderEditor(f: Field, value: any, onChange: (v: any) => void) {
    if (f.type === "category")
      return <Select value={value ?? ""} onChange={(e) => onChange(e.target.value)}><option value="">Kategori</option>{COST_CATEGORY_OPTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</Select>;
    if (f.type === "status")
      return <Select value={value ?? "unpaid"} onChange={(e) => onChange(e.target.value)}><option value="unpaid">Ödenmedi</option><option value="paid">Ödendi</option></Select>;
    if (f.type === "ownership")
      return <Select value={value ?? "rented"} onChange={(e) => onChange(e.target.value)}><option value="rented">Kiralık</option><option value="owned">Şirkete Ait</option></Select>;
    if (f.type === "unit")
      return <Select value={value ?? "day"} onChange={(e) => onChange(e.target.value)}><option value="day">Gün</option><option value="month">Ay</option></Select>;
    if (f.type === "vat")
      return <Select value={value ?? "20"} onChange={(e) => onChange(e.target.value)}>{[0, 1, 10, 20].map((v) => <option key={v} value={v}>%{v}</option>)}</Select>;
    return <Input type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-bg">
      <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
        <h2 className="flex items-center gap-2 text-lg font-bold text-primary"><Sparkles className="h-5 w-5 text-accent" /> AI ile İçe Aktarma</h2>
        <button onClick={onClose} className="text-text-secondary hover:text-text-primary"><X className="h-5 w-5" /></button>
      </div>

      {loading ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-text-secondary">
          <Sparkles className="h-8 w-8 animate-pulse text-accent" /> AI dosyanızı analiz ediyor... (genellikle 10-30 saniye)
        </div>
      ) : (
        <>
          <div className="flex gap-1 border-b border-border bg-surface px-6">
            {TABS.map((t) => (
              <button key={t.key} onClick={() => { setTab(t.key); setEditingRow(null); }} className={cn("border-b-2 px-3 py-2 text-sm", tab === t.key ? "border-primary font-semibold text-primary" : "border-transparent text-text-secondary")}>
                {t.label} ({(extracted[t.key] ?? []).length})
              </button>
            ))}
          </div>
          {analysis?.truncated && <div className="bg-amber-50 px-6 py-2 text-xs">Dosyanızın ilk 500 satırı işlendi. Kalan veriler için tekrar yükleyin.</div>}

          <div className="flex-1 overflow-auto p-6">
            {rows.length === 0 ? (
              <p className="text-sm text-text-secondary">Bu kategoride kayıt bulunamadı.</p>
            ) : (
              <div className="space-y-2">
                {rows.map((r, i) => {
                  const isEditing = editingRow === i;
                  const lowConf = toNumber(r.confidence) < 0.6;
                  return (
                    <div key={i} className={cn("rounded-md border bg-surface p-3", (tab === "tanimsiz" || lowConf) && "bg-amber-50")}>
                      <div className="mb-2 flex items-center justify-between">
                        <ConfidenceChip c={toNumber(r.confidence)} />
                        <div className="flex gap-2">
                          {!isEditing && tab !== "tanimsiz" && <button onClick={() => setEditingRow(i)} className="text-text-secondary hover:text-primary" aria-label="Düzenle"><Pencil className="h-4 w-4" /></button>}
                          <button onClick={() => deleteRow(i)} className="text-text-secondary hover:text-danger" aria-label="Sil"><Trash2 className="h-4 w-4" /></button>
                        </div>
                      </div>
                      {isEditing ? (
                        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                          {fields.map((f) => (
                            <div key={f.key}>
                              <label className="mb-0.5 block text-[11px] text-text-secondary">{f.label}</label>
                              {renderEditor(f, r[f.key], (v) => updateRow(i, f.key, v))}
                            </div>
                          ))}
                          <div className="col-span-full flex justify-end">
                            <Button variant="outline" className="px-3 py-1 text-xs" onClick={() => setEditingRow(null)}>Tamam</Button>
                          </div>
                        </div>
                      ) : (
                        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm md:grid-cols-4">
                          {fields.map((f) => (
                            <div key={f.key} className="truncate">
                              <span className="text-text-secondary">{f.label}: </span>
                              <span className="font-medium">{displayValue(f, r[f.key])}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                {tab !== "tanimsiz" && <Button variant="outline" onClick={addRow}><Plus className="h-4 w-4" /> Satır Ekle</Button>}
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
