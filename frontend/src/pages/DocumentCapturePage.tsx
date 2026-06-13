import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody, Input, Label, Select } from "@/components/ui";
import { COST_CATEGORIES, VAT_RATES } from "@/constants";
import { useFetch } from "@/hooks/useFetch";
import { api, apiPost } from "@/lib/api";
import { useProjectStore } from "@/store/project";
import { toast } from "@/store/toast";
import type { Project } from "@/types";
import { Camera, CheckCircle2, Loader2, Sparkles, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

type Extracted = {
  supplier_name?: string | null;
  invoice_number?: string | null;
  invoice_date?: string | null;
  amount_try?: number | string | null;
  vat_rate?: number | string | null;
  description?: string | null;
  cost_category?: string | null;
  confidence?: number | null;
};

type Form = {
  supplier_name: string;
  invoice_number: string;
  entry_date: string;
  amount_try: string;
  vat_rate: string;
  cost_category: string;
  description: string;
  payment_due_date: string;
  payment_status: string;
};

const today = () => new Date().toISOString().slice(0, 10);

function blank(): Form {
  return {
    supplier_name: "",
    invoice_number: "",
    entry_date: today(),
    amount_try: "",
    vat_rate: "20",
    cost_category: "material_other",
    description: "",
    payment_due_date: "",
    payment_status: "unpaid",
  };
}

export default function DocumentCapturePage() {
  const navigate = useNavigate();
  const { data: projects } = useFetch<Project[]>("/projects");
  const { activeProjectId } = useProjectStore();
  const [projectId, setProjectId] = useState(activeProjectId ?? "");
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [preview, setPreview] = useState<string | null>(null);
  const [isPdf, setIsPdf] = useState(false);
  const [reading, setReading] = useState(false);
  const [docPath, setDocPath] = useState<string | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (k: keyof Form, v: string) => setForm((f) => (f ? { ...f, [k]: v } : f));

  const activeProjects = (projects ?? []).filter((p: any) => p.status === "active");

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    if (!projectId) {
      toast.error("Önce bir proje seçin");
      return;
    }
    setIsPdf(file.type === "application/pdf");
    setPreview(file.type === "application/pdf" ? null : URL.createObjectURL(file));
    setForm(null);
    setConfidence(null);
    setDocPath(null);
    setReading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post(`/projects/${projectId}/document-capture`, fd);
      const { extracted, document_path } = res.data.data as { extracted: Extracted; document_path: string };
      setDocPath(document_path);
      setConfidence(typeof extracted.confidence === "number" ? extracted.confidence : null);
      const f = blank();
      if (extracted.supplier_name) f.supplier_name = String(extracted.supplier_name);
      if (extracted.invoice_number) f.invoice_number = String(extracted.invoice_number);
      if (extracted.invoice_date) f.entry_date = String(extracted.invoice_date);
      if (extracted.amount_try != null) f.amount_try = String(extracted.amount_try);
      if (extracted.vat_rate != null) f.vat_rate = String(extracted.vat_rate);
      if (extracted.description) f.description = String(extracted.description);
      if (extracted.cost_category && COST_CATEGORIES[String(extracted.cost_category)]) f.cost_category = String(extracted.cost_category);
      setForm(f);
    } catch (err: any) {
      toast.error(err.message ?? "Belge okunamadı");
      setForm(blank());
    } finally {
      setReading(false);
    }
  };

  const save = async () => {
    if (!form || !projectId) return;
    if (!form.amount_try || Number(form.amount_try) <= 0) {
      toast.error("Geçerli bir tutar girin");
      return;
    }
    setSaving(true);
    try {
      await apiPost(`/projects/${projectId}/document-capture/confirm`, {
        document_path: docPath,
        entry_date: form.entry_date,
        cost_category: form.cost_category,
        supplier_name: form.supplier_name || null,
        invoice_number: form.invoice_number || null,
        description: form.description || null,
        amount_try: form.amount_try,
        vat_rate: form.vat_rate,
        payment_due_date: form.payment_due_date || null,
        payment_status: form.payment_status,
      });
      toast.success("Maliyet girişi kaydedildi");
      setForm(null);
      setPreview(null);
      setDocPath(null);
      setConfidence(null);
    } catch (err: any) {
      toast.error(err.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const conf = confidence != null ? Math.round(confidence * 100) : null;
  const confColor = conf == null ? "" : conf >= 80 ? "text-success" : conf >= 50 ? "text-accent" : "text-danger";

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader title="Belge Tara" subtitle="Fatura fotoğrafını çek, yapay zeka maliyet girişini hazırlasın" />

      <Card>
        <CardBody className="space-y-3">
          <div>
            <Label required>Proje</Label>
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">Proje seçin…</option>
              {activeProjects.map((p: any) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </Select>
          </div>

          {preview && (
            <img src={preview} alt="Önizleme" className="max-h-56 w-full rounded-md border border-border object-contain" />
          )}
          {isPdf && !preview && (
            <div className="rounded-md border border-border bg-bg px-3 py-2 text-sm text-text-secondary">PDF yüklendi</div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <Button type="button" variant="outline" onClick={() => cameraRef.current?.click()} disabled={reading || !projectId}>
              <Camera className="h-4 w-4" /> Fotoğraf Çek
            </Button>
            <Button type="button" variant="outline" onClick={() => fileRef.current?.click()} disabled={reading || !projectId}>
              <Upload className="h-4 w-4" /> Dosya Seç
            </Button>
          </div>
          <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onPick} />
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,application/pdf" className="hidden" onChange={onPick} />

          {reading && (
            <div className="flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-accent">
              <Loader2 className="h-4 w-4 animate-spin" /> Yapay zeka belgeyi okuyor…
            </div>
          )}
        </CardBody>
      </Card>

      {form && (
        <Card className="mt-4">
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-primary">
                <Sparkles className="h-4 w-4 text-brand" /> Çıkarılan Bilgiler
              </h3>
              {conf != null && <span className={`text-xs font-semibold ${confColor}`}>Güven: %{conf}</span>}
            </div>
            <p className="text-xs text-text-secondary">Kaydetmeden önce kontrol edip düzeltin. Kayıt, seçtiğiniz projenin giderlerine eklenir.</p>

            <div><Label>Tedarikçi</Label><Input value={form.supplier_name} onChange={(e) => set("supplier_name", e.target.value)} /></div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label>Fatura No</Label><Input value={form.invoice_number} onChange={(e) => set("invoice_number", e.target.value)} /></div>
              <div><Label required>Tarih</Label><Input type="date" value={form.entry_date} onChange={(e) => set("entry_date", e.target.value)} /></div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label required>Tutar (KDV hariç ₺)</Label><Input type="number" value={form.amount_try} onChange={(e) => set("amount_try", e.target.value)} /></div>
              <div><Label>KDV %</Label><Select value={form.vat_rate} onChange={(e) => set("vat_rate", e.target.value)}>{VAT_RATES.map((v) => <option key={v} value={v}>%{v}</option>)}</Select></div>
            </div>
            <div><Label required>Maliyet Kategorisi</Label>
              <Select value={form.cost_category} onChange={(e) => set("cost_category", e.target.value)}>
                {Object.entries(COST_CATEGORIES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </Select>
            </div>
            <div><Label>Açıklama</Label><Input value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label>Vade Tarihi</Label><Input type="date" value={form.payment_due_date} onChange={(e) => set("payment_due_date", e.target.value)} /></div>
              <div><Label>Ödeme Durumu</Label>
                <Select value={form.payment_status} onChange={(e) => set("payment_status", e.target.value)}>
                  <option value="unpaid">Ödenmedi</option>
                  <option value="paid">Ödendi</option>
                </Select>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => navigate(`/projects/${projectId}/budget`)}>İptal</Button>
              <Button type="button" onClick={save} loading={saving}><CheckCircle2 className="h-4 w-4" /> Maliyet Olarak Kaydet</Button>
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
