import { Button, Input, Select } from "@/components/ui";
import { COST_CATEGORY_OPTIONS } from "@/constants";
import { api, apiPost } from "@/lib/api";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import { formatCurrency, toNumber } from "@/utils/format";
import { Plus, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

interface Row {
  entry_date: string;
  cost_category: string;
  subcategory?: string;
  supplier_name?: string;
  description?: string;
  invoice_number?: string;
  amount_try: string;
  vat_rate: string;
  payment_due_date?: string;
  payment_status?: string;
  date_paid?: string;
}

const CATEGORY_KEYS = new Set(COST_CATEGORY_OPTIONS.map((c) => c.value));

// CR-006-F: Türkçe doğrulama mesajları (backend ile aynı ifadeler).
function rowErrors(r: Row): string[] {
  const errs: string[] = [];
  if (!r.entry_date) errs.push("Geçersiz tarih formatı — DD.MM.YYYY kullanın");
  if (!r.cost_category || !CATEGORY_KEYS.has(r.cost_category)) errs.push("Kategori tanınmıyor");
  const amt = r.amount_try?.toString().trim() ?? "";
  if (amt !== "" && Number.isNaN(Number(amt.replace(",", ".")))) {
    errs.push("Tutar sayısal olmalı — para birimi sembolü girmeyin");
  } else if (toNumber(r.amount_try) <= 0) {
    errs.push("Tutar 0'dan büyük olmalı");
  }
  if (r.entry_date && r.payment_due_date && r.payment_due_date < r.entry_date) {
    errs.push("Vade tarihi fatura tarihinden önce olamaz");
  }
  return errs;
}

// CR-001-F + CR-002-F: sheet picker -> preview with header/total detection.
export function ImportPreview({
  projectId,
  file,
  onClose,
  onDone,
}: {
  projectId: string;
  file: File;
  onClose: () => void;
  onDone: () => void;
}) {
  const [phase, setPhase] = useState<"loading" | "sheet" | "preview">("loading");
  const [sheets, setSheets] = useState<string[]>([]);
  const [selectedSheet, setSelectedSheet] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [skippedCount, setSkippedCount] = useState(0);
  const [saving, setSaving] = useState(false);

  // Step 1: list sheets; if only one, go straight to preview.
  useEffect(() => {
    const fd = new FormData();
    fd.append("file", file);
    api
      .post(`/projects/${projectId}/costs/import/sheets`, fd)
      .then((res) => {
        const s: string[] = res.data.data.sheets ?? [];
        setSheets(s);
        if (s.length <= 1) loadPreview(s[0]);
        else setPhase("sheet");
      })
      .catch((e) => {
        toast.error(e.message ?? "Dosya okunamadı");
        onClose();
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, projectId]);

  const loadPreview = (sheet?: string) => {
    setPhase("loading");
    if (sheet) setSelectedSheet(sheet);
    const fd = new FormData();
    fd.append("file", file);
    if (sheet) fd.append("sheet_name", sheet);
    api
      .post(`/projects/${projectId}/costs/import/preview`, fd)
      .then((res) => {
        const data = res.data.data ?? [];
        const meta = res.data.meta ?? {};
        // CR-002-F: skipped rows (header/total/empty-date) are excluded from the editable list.
        const editable = data.filter((r: any) => !r.skipped).map((r: any) => ({ ...r.data, vat_rate: r.data.vat_rate ?? "20" }));
        setRows(editable);
        setSkippedCount(meta.skipped ?? 0);
        if (meta.header_detected === false) {
          toast.info("Başlık satırı tespit edilemedi. Lütfen verileri kontrol edin.");
        }
        setPhase("preview");
      })
      .catch((e) => {
        toast.error(e.message ?? "Önizleme oluşturulamadı");
        onClose();
      });
  };

  const computed = useMemo(() => rows.map((r) => ({ ...r, _errors: rowErrors(r) })), [rows]);
  const validCount = computed.filter((r) => r._errors.length === 0).length;
  const invalidCount = computed.length - validCount;
  const totalAmount = computed.reduce((s, r) => s + toNumber(r.amount_try), 0);

  const update = (i: number, k: keyof Row, v: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const removeRow = (i: number) => setRows((rs) => rs.filter((_, j) => j !== i));
  const addRow = () => setRows((rs) => [...rs, { entry_date: new Date().toISOString().slice(0, 10), cost_category: "", amount_try: "", vat_rate: "20" }]);

  const confirm = async () => {
    if (invalidCount > 0) return;
    setSaving(true);
    try {
      const payload = computed.map((r) => ({
        entry_date: r.entry_date,
        cost_category: r.cost_category,
        subcategory: r.subcategory || null,
        supplier_name: r.supplier_name || null,
        description: r.description || null,
        invoice_number: r.invoice_number || null,
        amount_try: r.amount_try,
        vat_rate: r.vat_rate || "20",
        payment_due_date: r.payment_due_date || null,
        payment_status: r.payment_status || "unpaid",
        date_paid: r.date_paid || null,
      }));
      const res = await apiPost<{ imported: number }>(`/projects/${projectId}/costs/import/confirm`, { rows: payload });
      toast.success(`${res.imported} satır içe aktarıldı`);
      onDone();
    } catch (e: any) {
      toast.error(e.message ?? "İçe aktarma başarısız");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-bg">
      {phase === "sheet" ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
          <button onClick={onClose} className="absolute right-6 top-6 text-text-secondary"><X className="h-5 w-5" /></button>
          <h2 className="text-lg font-bold text-primary">Excel dosyasında birden fazla sayfa bulundu</h2>
          <p className="text-sm text-text-secondary">Hangi sayfadan veri aktarmak istiyorsunuz?</p>
          <div className="flex flex-wrap justify-center gap-2">
            {sheets.map((s) => (
              <Button key={s} variant="outline" onClick={() => loadPreview(s)}>{s}</Button>
            ))}
          </div>
        </div>
      ) : phase === "loading" ? (
        <div className="flex flex-1 items-center justify-center text-sm text-text-secondary">Yükleniyor...</div>
      ) : (
        <>
          <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
            <div>
              <h2 className="text-lg font-bold text-primary">İçe Aktarma Önizlemesi — {computed.length} satır bulundu</h2>
              {selectedSheet && <p className="mt-0.5 text-xs text-text-secondary">Aktarılan sayfa: <b>{selectedSheet}</b></p>}
              <div className="mt-1 flex gap-4 text-sm">
                <span>Toplam: <b>{computed.length}</b></span>
                <span className="text-success">Geçerli: <b>{validCount}</b></span>
                <span className="text-danger">Hatalı: <b>{invalidCount}</b></span>
                {skippedCount > 0 && <span className="text-text-secondary">Atlanan: <b>{skippedCount}</b> (başlık/toplam)</span>}
                <span>Toplam Tutar: <b>{formatCurrency(totalAmount)}</b></span>
              </div>
            </div>
            <button onClick={onClose} className="text-text-secondary hover:text-text-primary"><X className="h-5 w-5" /></button>
          </div>

          <div className="flex-1 overflow-auto p-6">
            <div className="space-y-2">
              {computed.map((r, i) => (
                <div key={i} className={cn("rounded-md border bg-surface p-3", r._errors.length ? "border-l-4 border-l-danger" : "border-l-4 border-l-success")}>
                  <div className="grid grid-cols-2 gap-2 md:grid-cols-7">
                    <Input type="date" value={r.entry_date ?? ""} onChange={(e) => update(i, "entry_date", e.target.value)} />
                    <Select value={r.cost_category ?? ""} onChange={(e) => update(i, "cost_category", e.target.value)}>
                      <option value="">Kategori</option>
                      {COST_CATEGORY_OPTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                    </Select>
                    <Input placeholder="Tedarikçi" value={r.supplier_name ?? ""} onChange={(e) => update(i, "supplier_name", e.target.value)} />
                    <Input placeholder="Açıklama" value={r.description ?? ""} onChange={(e) => update(i, "description", e.target.value)} />
                    <Input type="number" placeholder="Tutar" value={r.amount_try ?? ""} onChange={(e) => update(i, "amount_try", e.target.value)} />
                    <Select value={r.vat_rate ?? "20"} onChange={(e) => update(i, "vat_rate", e.target.value)}>
                      {[0, 1, 10, 20].map((v) => <option key={v} value={v}>%{v}</option>)}
                    </Select>
                    <div className="flex items-center justify-end">
                      <button onClick={() => removeRow(i)} className="text-text-secondary hover:text-danger" aria-label="Satırı sil"><Trash2 className="h-4 w-4" /></button>
                    </div>
                  </div>
                  {r._errors.length > 0 && <p className="mt-1 text-xs text-danger">{r._errors.join(" · ")}</p>}
                </div>
              ))}
              <Button variant="outline" onClick={addRow}><Plus className="h-4 w-4" /> Satır Ekle</Button>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-border bg-surface px-6 py-3">
            <Button variant="ghost" onClick={onClose}>İptal</Button>
            <Button onClick={confirm} loading={saving} disabled={invalidCount > 0 || computed.length === 0}>İçe Aktar ({validCount} satır)</Button>
          </div>
        </>
      )}
    </div>
  );
}
