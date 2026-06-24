import { Button, Card, CardBody, Input, Label, Select, Switch } from "@/components/ui";
import { COST_CATEGORIES, VAT_RATES } from "@/constants";
import { api, apiPost } from "@/lib/api";
import { toast } from "@/store/toast";
import { formatCurrency, formatDate } from "@/utils/format";
import { AlertTriangle, ArrowRight, Camera, CheckCircle2, Copy, FileText, Loader2, ShieldCheck, Sparkles, Upload, Zap } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

interface LineItem {
  description?: string | null;
  quantity?: number | string | null;
  unit_price?: number | string | null;
  amount?: number | string | null;
}

interface Extracted {
  supplier_name?: string | null;
  invoice_number?: string | null;
  invoice_date?: string | null;
  due_date?: string | null;
  currency?: string | null;
  subtotal?: number | string | null;
  vat_amount?: number | string | null;
  vat_rate?: number | string | null;
  total?: number | string | null;
  line_items?: LineItem[] | null;
  confidence?: number | null;
  suggested_project_id?: string | null;
  suggested_cost_category?: string | null;
  suggested_destination?: string | null;
  suggested_equipment_name?: string | null;
  reasoning?: string | null;
}

interface ProjectOpt { id: string; name: string }

interface DupItem { id: string; supplier?: string | null; invoice_number?: string | null; amount_try: string; entry_date: string; project?: string | null; reasons: string[] }
interface AnomalyItem { type: string; message: string }

// Where a captured document is filed. The AI suggests it; the user confirms.
type Destination = "cost" | "equipment" | "income";
const DESTINATIONS: { key: Destination; label: string }[] = [
  { key: "cost", label: "Gider" },
  { key: "equipment", label: "Ekipman" },
  { key: "income", label: "Gelir / Hakediş" },
];

type Form = {
  // shared
  supplier_name: string;
  invoice_number: string;
  entry_date: string;
  amount_try: string;
  vat_rate: string;
  description: string;
  // cost (Gider)
  cost_category: string;
  payment_due_date: string;
  payment_status: string;
  // equipment (Ekipman)
  equipment_name: string;
  ownership_type: string;
  rate_try: string;
  rate_unit: string;
  deployment_start: string;
  deployment_end: string;
  fuel_maintenance_try: string;
  add_to_budget: boolean;
  // income (Gelir / Hakediş)
  due_date: string;
  hakkedis_period: string;
  retention_amount_try: string;
};

const today = () => new Date().toISOString().slice(0, 10);

/** Normalise any AI-returned date string to YYYY-MM-DD (what <input type=date> needs). */
function toISODate(s: unknown): string {
  if (!s) return "";
  const str = String(s).trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(str)) return str.slice(0, 10);
  const m = str.match(/^(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{4})/); // DD.MM.YYYY / DD/MM/YYYY
  if (m) return `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  const dt = new Date(str);
  return Number.isNaN(dt.getTime()) ? "" : dt.toISOString().slice(0, 10);
}

function blank(): Form {
  return {
    supplier_name: "", invoice_number: "", entry_date: today(), amount_try: "", vat_rate: "20", description: "",
    cost_category: "material_other", payment_due_date: "", payment_status: "unpaid",
    equipment_name: "", ownership_type: "rented", rate_try: "", rate_unit: "day",
    deployment_start: today(), deployment_end: "", fuel_maintenance_try: "0", add_to_budget: true,
    due_date: "", hakkedis_period: "", retention_amount_try: "0",
  };
}

export default function DocumentCapturePage() {
  const navigate = useNavigate();
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [preview, setPreview] = useState<string | null>(null);
  const [isPdf, setIsPdf] = useState(false);
  const [reading, setReading] = useState(false);
  const [docPath, setDocPath] = useState<string | null>(null);
  const [fileSha, setFileSha] = useState<string | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [destination, setDestination] = useState<Destination>("cost");
  const [suggestedDestination, setSuggestedDestination] = useState<Destination | null>(null);
  const [extracted, setExtracted] = useState<Extracted | null>(null);
  const [projects, setProjects] = useState<ProjectOpt[]>([]);
  const [projectId, setProjectId] = useState("");
  const [suggestedProjectId, setSuggestedProjectId] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<DupItem[]>([]);
  const [anomalies, setAnomalies] = useState<AnomalyItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  // CR-012 Template A — "Otomatik dosyalama" mode: uploads create approval
  // proposals instead of the manual review form (when uncertain, it falls back).
  const [autoMode, setAutoMode] = useState(false);
  const [proposed, setProposed] = useState<{ destination: string; confidence: number } | null>(null);
  const [fallbackReason, setFallbackReason] = useState<string | null>(null);

  const set = (k: keyof Form, v: string | boolean) => setForm((f) => (f ? { ...f, [k]: v } : f));

  const ACCEPTED = ["image/png", "image/jpeg", "application/pdf"];

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) processFile(file);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (reading) return;
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (!ACCEPTED.includes(file.type)) {
      toast.error("Yalnızca JPEG, PNG veya PDF yükleyebilirsiniz");
      return;
    }
    processFile(file);
  };

  const processFile = async (file: File) => {
    setIsPdf(file.type === "application/pdf");
    setPreview(file.type === "application/pdf" ? null : URL.createObjectURL(file));
    setForm(null);
    setExtracted(null);
    setDocPath(null);
    setDuplicates([]);
    setAnomalies([]);
    setProposed(null);
    setFallbackReason(null);
    setReading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post(autoMode ? `/document-capture/auto-file` : `/document-capture`, fd);
      const d = res.data.data as any;
      // Auto-file: a high-confidence in-subset doc becomes a pending approval —
      // nothing is shown to edit here; it waits for a human in Onay Bekleyenler.
      if (d.mode === "proposed") {
        setProposed({ destination: d.destination, confidence: d.confidence });
        setPreview(null);
        setIsPdf(false);
        toast.success("Öneri Onay Bekleyenler'e eklendi.");
        return;
      }
      if (d.fallback_reason) setFallbackReason(d.fallback_reason);
      const { extracted, document_path, file_sha256, projects, duplicates, anomalies } = d as {
        extracted: Extracted; document_path: string; file_sha256: string; projects: ProjectOpt[];
        duplicates?: DupItem[]; anomalies?: AnomalyItem[];
      };
      setExtracted(extracted);
      setDuplicates(duplicates ?? []);
      setAnomalies(anomalies ?? []);
      setDocPath(document_path);
      setFileSha(file_sha256);
      setProjects(projects ?? []);
      const sug = extracted.suggested_project_id && (projects ?? []).some((p) => p.id === extracted.suggested_project_id)
        ? String(extracted.suggested_project_id) : "";
      setSuggestedProjectId(sug || null);
      setProjectId(sug);
      const f = blank();
      if (extracted.supplier_name) f.supplier_name = String(extracted.supplier_name);
      if (extracted.invoice_number) f.invoice_number = String(extracted.invoice_number);
      const invDate = toISODate(extracted.invoice_date);
      if (invDate) f.entry_date = invDate;
      f.payment_due_date = toISODate(extracted.due_date);
      if (extracted.subtotal != null) f.amount_try = String(extracted.subtotal);
      if (extracted.vat_rate != null) f.vat_rate = String(extracted.vat_rate);
      if (extracted.suggested_cost_category && COST_CATEGORIES[String(extracted.suggested_cost_category)]) f.cost_category = String(extracted.suggested_cost_category);
      const firstLine = extracted.line_items?.[0]?.description;
      if (firstLine) f.description = String(firstLine);
      // Equipment prefill: a captured doc rarely states ownership/rate cleanly, so
      // fall back to sensible defaults the user can adjust before confirming.
      if (extracted.suggested_equipment_name) f.equipment_name = String(extracted.suggested_equipment_name);
      else if (firstLine) f.equipment_name = String(firstLine);
      if (invDate) f.deployment_start = invDate;
      // Income prefill: due_date defaults to the invoice date (the user can extend it).
      f.due_date = toISODate(extracted.due_date) || invDate || f.due_date;
      // AI-suggested destination, confirmed by the user below. Default "cost".
      const sd = String(extracted.suggested_destination || "cost") as Destination;
      const dest: Destination = sd === "equipment" || sd === "income" ? sd : "cost";
      setSuggestedDestination(dest);
      setDestination(dest);
      setForm(f);
    } catch (err: any) {
      toast.error(err.message ?? "Belge okunamadı");
      setForm(blank());
    } finally {
      setReading(false);
    }
  };

  const save = async () => {
    if (!form) return;
    if (!projectId) { toast.error("Lütfen bir proje seçin"); return; }

    let body: Record<string, unknown>;
    let successMsg: string;
    if (destination === "equipment") {
      if (!form.equipment_name.trim()) { toast.error("Ekipman adı girin"); return; }
      if (!form.deployment_start) { toast.error("Başlangıç tarihi girin"); return; }
      if (form.ownership_type === "rented" && form.add_to_budget && (!form.rate_try || Number(form.rate_try) <= 0)) {
        toast.error("Bütçeye eklemek için birim ücret girin (veya bütçeye eklemeyi kapatın)"); return;
      }
      body = {
        project_id: projectId, destination: "equipment", document_path: docPath, file_sha256: fileSha,
        equipment_name: form.equipment_name, ownership_type: form.ownership_type,
        supplier_name: form.supplier_name || null,
        rate_try: form.rate_try || null, rate_unit: form.rate_unit || null,
        deployment_start: form.deployment_start, deployment_end: form.deployment_end || null,
        fuel_maintenance_try: form.fuel_maintenance_try || "0", add_to_budget: form.add_to_budget,
      };
      successMsg = "Ekipman kaydı oluşturuldu";
    } else if (destination === "income") {
      if (!form.invoice_number.trim()) { toast.error("Fatura no girin"); return; }
      if (!form.entry_date) { toast.error("Fatura tarihi girin"); return; }
      if (!form.due_date) { toast.error("Vade tarihi girin"); return; }
      if (!form.amount_try || Number(form.amount_try) <= 0) { toast.error("Geçerli bir tutar girin"); return; }
      body = {
        project_id: projectId, destination: "income", document_path: docPath, file_sha256: fileSha,
        invoice_number: form.invoice_number, invoice_date: form.entry_date, due_date: form.due_date,
        hakkedis_period: form.hakkedis_period || null, description: form.description || null,
        amount_try: form.amount_try, vat_rate: form.vat_rate,
        retention_amount_try: form.retention_amount_try || "0",
      };
      successMsg = "Hakediş / gelir kaydı oluşturuldu";
    } else {
      if (!form.amount_try || Number(form.amount_try) <= 0) { toast.error("Geçerli bir tutar girin"); return; }
      body = {
        project_id: projectId, destination: "cost", document_path: docPath, file_sha256: fileSha,
        entry_date: form.entry_date, cost_category: form.cost_category,
        supplier_name: form.supplier_name || null, invoice_number: form.invoice_number || null,
        description: form.description || null, amount_try: form.amount_try, vat_rate: form.vat_rate,
        payment_due_date: form.payment_due_date || null, payment_status: form.payment_status,
      };
      successMsg = "Maliyet girişi kaydedildi";
    }

    setSaving(true);
    try {
      await apiPost(`/document-capture/confirm`, body);
      toast.success(successMsg);
      setForm(null);
      setExtracted(null);
      setPreview(null);
      setDocPath(null);
      setDuplicates([]);
      setAnomalies([]);
    } catch (err: any) {
      toast.error(err.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const conf = extracted?.confidence != null ? Math.round(extracted.confidence * 100) : null;
  const confColor = conf == null ? "" : conf >= 80 ? "text-success" : conf >= 50 ? "text-accent" : "text-danger";
  const currency = (extracted?.currency || "TRY").toUpperCase();
  const lineItems = extracted?.line_items ?? [];

  return (
    <div className="mx-auto max-w-2xl">
      {/* AI hero — what it is, that it uses AI, and what it does */}
      <div className="overflow-hidden rounded-2xl bg-gradient-to-br from-[#1e3a8a] via-[#2563eb] to-[#0891b2] p-5 text-white shadow-sm">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/15">
            <Sparkles className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold">Akıllı Belge Tarama</h1>
              <span className="rounded-full bg-white/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">Yapay Zeka</span>
            </div>
            <p className="mt-0.5 text-[13px] leading-snug text-white/85">
              Fatura fotoğrafını veya PDF'ini yükleyin. <b>Yapı AI</b> belgeyi okur, bilgileri çıkarır,
              doğru proje ve maliyet kodunu gerekçesiyle önerir ve mükerrer/anormal kayıtları yakalar.
            </p>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {[
            { icon: FileText, title: "Otomatik Çıkarım", desc: "Tedarikçi, fatura no, tarih, vade, KDV, toplam ve satır kalemleri." },
            { icon: Sparkles, title: "Akıllı Sınıflandırma", desc: "Tedarikçi geçmişi ve bütçeye göre proje + maliyet kodu önerisi — gerekçeli." },
            { icon: ShieldCheck, title: "Mükerrer & Anomali", desc: "Aynı fatura/tutar veya olağandışı maliyetleri otomatik kontrol eder." },
          ].map((f) => (
            <div key={f.title} className="rounded-lg bg-white/10 p-2.5">
              <div className="flex items-center gap-1.5 text-[13px] font-semibold">
                <f.icon className="h-3.5 w-3.5 text-brand-2" /> {f.title}
              </div>
              <p className="mt-0.5 text-[11px] leading-snug text-white/80">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CR-012 Template A — mode toggle: manual review vs auto-file proposals. */}
      <div className="mt-4 flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3 shadow-sm">
        <div className="flex items-start gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy-50 text-brand">
            <Zap className="h-4 w-4" />
          </span>
          <div>
            <p className="text-sm font-semibold text-primary">Otomatik dosyalama</p>
            <p className="text-[11px] leading-snug text-text-secondary">
              Açıkken Yapı AI belgeyi sınıflandırır ve emin olduğunda doğrudan{" "}
              <b>Onay Bekleyenler</b>'e öneri olarak ekler. Belirsizse elle incelemeye düşer.
            </p>
          </div>
        </div>
        <Switch checked={autoMode} onChange={setAutoMode} label="Otomatik dosyalama modu" />
      </div>

      {/* Proposed banner — auto-file created a pending approval. */}
      {proposed && (
        <div className="mt-3 flex items-center gap-3 rounded-xl border border-success/40 bg-green-50 px-4 py-3">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-success" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-success">Öneri Onay Bekleyenler'e eklendi</p>
            <p className="text-[11px] text-text-secondary">
              {proposed.destination === "cost" ? "Gider" : "Hakediş"} olarak önerildi · güven %
              {Math.round((proposed.confidence ?? 0) * 100)}. Onayladığınızda kayıt oluşturulur.
            </p>
          </div>
          <Button variant="outline" className="shrink-0 px-3 py-1.5 text-xs" onClick={() => navigate("/approvals")}>
            Onay Bekleyenler <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {/* Upload zone */}
      <div className="mt-4">
        <div className="rounded-xl border border-border bg-surface p-5 text-center shadow-sm">
          <span className="mx-auto mb-2 flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-brand to-brand-2 text-white shadow-sm">
            <Sparkles className="h-5 w-5" />
          </span>
          <p className="text-sm font-medium text-primary">Faturayı yükleyin, gerisini Yapı AI halletsin</p>

          {/* Grey drag-and-drop section */}
          <div
            onDragOver={(e) => { e.preventDefault(); if (!reading) setDragOver(true); }}
            onDragLeave={(e) => { e.preventDefault(); setDragOver(false); }}
            onDrop={onDrop}
            className={`my-4 flex min-h-[225px] flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed p-4 transition-colors ${
              dragOver ? "border-brand bg-navy-50 ring-2 ring-brand/30" : "border-border bg-bg"
            }`}
          >
            {preview ? (
              <img src={preview} alt="Önizleme" className="mx-auto max-h-48 w-full rounded-md border border-border object-contain" />
            ) : isPdf ? (
              <div className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-secondary">PDF yüklendi</div>
            ) : (
              <>
                <Upload className="mb-1 h-7 w-7 text-text-secondary" />
                <p className="text-sm font-medium text-text-primary">Dosyayı buraya sürükleyip bırakın</p>
                <p className="text-xs text-text-secondary">veya aşağıdaki butonları kullanın</p>
                <p className="mt-1 text-xs text-text-secondary">JPEG, PNG veya PDF · en fazla 10MB</p>
              </>
            )}
          </div>

          <div className="mx-auto flex max-w-sm flex-col gap-2 sm:flex-row">
            <Button type="button" variant="outline" className="flex-1" onClick={() => cameraRef.current?.click()} disabled={reading}>
              <Camera className="h-4 w-4" /> Fotoğraf Çek
            </Button>
            <Button type="button" className="flex-1" onClick={() => fileRef.current?.click()} disabled={reading}>
              <Upload className="h-4 w-4" /> Dosya Seç
            </Button>
          </div>
          <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onPick} />
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,application/pdf" className="hidden" onChange={onPick} />

          {reading && (
            <div className="mt-3 flex items-center justify-center gap-2 rounded-md bg-navy-50 px-3 py-2 text-sm text-brand">
              <Loader2 className="h-4 w-4 animate-spin" /> Yapı AI belgeyi okuyor ve sınıflandırıyor…
            </div>
          )}
        </div>
      </div>

      {form && fallbackReason && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-warning/40 bg-amber-50 px-3 py-2 text-xs text-text-secondary">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
          {fallbackReason === "low_confidence"
            ? "Yapı AI bu belgeden yeterince emin olamadı — lütfen alanları kontrol edip elle kaydedin."
            : "Bu belge türü otomatik dosyalama kapsamı dışında — lütfen elle inceleyin."}
        </div>
      )}

      {form && (
        <Card className="mt-4">
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-primary">
                <Sparkles className="h-4 w-4 text-brand" /> Çıkarılan Bilgiler
              </h3>
              {conf != null && <span className={`text-xs font-semibold ${confColor}`}>Güven: %{conf}</span>}
            </div>

            {/* Duplicate warnings */}
            {duplicates.length > 0 && (
              <div className="rounded-lg border border-danger/40 bg-red-50 px-3 py-2 text-xs">
                <div className="flex items-center gap-1.5 font-semibold text-danger">
                  <Copy className="h-3.5 w-3.5" /> Olası mükerrer kayıt ({duplicates.length})
                </div>
                <ul className="mt-1.5 space-y-1.5">
                  {duplicates.map((d) => (
                    <li key={d.id}>
                      <span className="font-medium text-text-primary">
                        {[d.supplier || "—", d.invoice_number, formatCurrency(d.amount_try), formatDate(d.entry_date)].filter(Boolean).join(" · ")}
                      </span>
                      {d.project && <span className="text-text-secondary"> · {d.project}</span>}
                      <div className="text-[11px] text-danger">{d.reasons.join(" · ")}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Anomaly warnings */}
            {anomalies.length > 0 && (
              <div className="rounded-lg border border-warning/40 bg-amber-50 px-3 py-2 text-xs">
                <div className="flex items-center gap-1.5 font-semibold text-warning">
                  <AlertTriangle className="h-3.5 w-3.5" /> Dikkat ({anomalies.length})
                </div>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-text-secondary">
                  {anomalies.map((a, i) => <li key={i}>{a.message}</li>)}
                </ul>
              </div>
            )}

            {/* AI reasoning for the project + cost-code suggestion */}
            {extracted?.reasoning && (
              <div className="rounded-lg border border-brand/30 bg-navy-50 px-3 py-2 text-xs leading-relaxed text-text-primary">
                <span className="font-semibold text-brand">AI önerisi: </span>{extracted.reasoning}
              </div>
            )}

            {/* Destination picker — AI suggests, user confirms (cost / equipment / income) */}
            <div>
              <Label>Belge Hedefi {suggestedDestination && destination === suggestedDestination && <span className="ml-1 rounded-full bg-navy-50 px-1.5 py-0.5 text-[10px] font-medium text-brand">AI önerisi</span>}</Label>
              <div className="grid grid-cols-3 gap-2">
                {DESTINATIONS.map((d) => (
                  <button
                    key={d.key}
                    type="button"
                    onClick={() => setDestination(d.key)}
                    className={`rounded-lg border px-2 py-2 text-xs font-semibold transition-colors ${
                      destination === d.key ? "border-brand bg-navy-50 text-brand ring-1 ring-brand/30" : "border-border bg-surface text-text-secondary hover:border-brand/40"
                    }`}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Suggested project (editable) */}
            <div>
              <Label required>Proje {suggestedProjectId && projectId === suggestedProjectId && <span className="ml-1 rounded-full bg-navy-50 px-1.5 py-0.5 text-[10px] font-medium text-brand">AI önerisi</span>}</Label>
              <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">Proje seçin…</option>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </div>

            {/* --- Gider (cost) fields --- */}
            {destination === "cost" && <>
              <div><Label>Tedarikçi</Label><Input value={form.supplier_name} onChange={(e) => set("supplier_name", e.target.value)} /></div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label>Fatura No</Label><Input value={form.invoice_number} onChange={(e) => set("invoice_number", e.target.value)} /></div>
                <div><Label required>Fatura Tarihi</Label><Input type="date" value={form.entry_date} onChange={(e) => set("entry_date", e.target.value)} /></div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label required>Tutar (KDV hariç ₺)</Label><Input type="number" value={form.amount_try} onChange={(e) => set("amount_try", e.target.value)} /></div>
                <div><Label>KDV %</Label><Select value={form.vat_rate} onChange={(e) => set("vat_rate", e.target.value)}>{VAT_RATES.map((v) => <option key={v} value={v}>%{v}</option>)}</Select></div>
              </div>
              <div><Label required>Maliyet Kategorisi {extracted?.suggested_cost_category === form.cost_category && <span className="ml-1 rounded-full bg-navy-50 px-1.5 py-0.5 text-[10px] font-medium text-brand">AI önerisi</span>}</Label>
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
            </>}

            {/* --- Ekipman (equipment) fields --- */}
            {destination === "equipment" && <>
              <div><Label required>Ekipman Adı</Label><Input value={form.equipment_name} onChange={(e) => set("equipment_name", e.target.value)} /></div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label required>Sahiplik</Label>
                  <Select value={form.ownership_type} onChange={(e) => set("ownership_type", e.target.value)}>
                    <option value="rented">Kiralık</option>
                    <option value="owned">Şirkete Ait</option>
                  </Select>
                </div>
                {form.ownership_type === "rented" && <div><Label>Tedarikçi</Label><Input value={form.supplier_name} onChange={(e) => set("supplier_name", e.target.value)} /></div>}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label>Birim Ücret (₺)</Label><Input type="number" value={form.rate_try} onChange={(e) => set("rate_try", e.target.value)} /></div>
                <div><Label>Birim</Label>
                  <Select value={form.rate_unit} onChange={(e) => set("rate_unit", e.target.value)}>
                    <option value="day">Gün</option>
                    <option value="month">Ay</option>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label required>Başlangıç</Label><Input type="date" value={form.deployment_start} onChange={(e) => set("deployment_start", e.target.value)} /></div>
                <div><Label>Bitiş</Label><Input type="date" value={form.deployment_end} onChange={(e) => set("deployment_end", e.target.value)} /></div>
              </div>
              <div><Label>Yakıt / Bakım (₺)</Label><Input type="number" value={form.fuel_maintenance_try} onChange={(e) => set("fuel_maintenance_try", e.target.value)} /></div>
              <div className="flex items-center justify-between rounded-lg border border-border bg-bg px-3 py-2">
                <div>
                  <p className="text-sm font-medium text-primary">Bütçeye ekle</p>
                  <p className="text-[11px] text-text-secondary">Bu ekipman için taahhüt edilmiş bir maliyet kaydı oluşturur (birim ücret gerekir).</p>
                </div>
                <Switch checked={form.add_to_budget} onChange={(v) => set("add_to_budget", v)} label="Bütçeye ekle" />
              </div>
            </>}

            {/* --- Gelir / Hakediş (income) fields --- */}
            {destination === "income" && <>
              <div className="grid grid-cols-2 gap-2">
                <div><Label required>Fatura No</Label><Input value={form.invoice_number} onChange={(e) => set("invoice_number", e.target.value)} /></div>
                <div><Label>Hakediş Dönemi</Label><Input value={form.hakkedis_period} onChange={(e) => set("hakkedis_period", e.target.value)} placeholder="örn. 2026-06" /></div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label required>Fatura Tarihi</Label><Input type="date" value={form.entry_date} onChange={(e) => set("entry_date", e.target.value)} /></div>
                <div><Label required>Vade Tarihi</Label><Input type="date" value={form.due_date} onChange={(e) => set("due_date", e.target.value)} /></div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label required>Tutar (KDV hariç ₺)</Label><Input type="number" value={form.amount_try} onChange={(e) => set("amount_try", e.target.value)} /></div>
                <div><Label>KDV %</Label><Select value={form.vat_rate} onChange={(e) => set("vat_rate", e.target.value)}>{VAT_RATES.map((v) => <option key={v} value={v}>%{v}</option>)}</Select></div>
              </div>
              <div><Label>Teminat / Kesinti (₺)</Label><Input type="number" value={form.retention_amount_try} onChange={(e) => set("retention_amount_try", e.target.value)} /></div>
              <div><Label>Açıklama</Label><Input value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
            </>}

            {/* Totals summary from extraction */}
            {(extracted?.subtotal != null || extracted?.total != null) && (
              <div className="flex flex-wrap gap-x-6 gap-y-1 rounded-md bg-bg px-3 py-2 text-xs text-text-secondary">
                {currency !== "TRY" && <span className="font-semibold text-warning">Para birimi: {currency} (sistem ₺ olarak kaydeder — kontrol edin)</span>}
                {extracted?.subtotal != null && <span>Ara Toplam: <b className="text-text-primary">{formatCurrency(extracted.subtotal)}</b></span>}
                {extracted?.vat_amount != null && <span>KDV: <b className="text-text-primary">{formatCurrency(extracted.vat_amount)}</b></span>}
                {extracted?.total != null && <span>Genel Toplam: <b className="text-text-primary">{formatCurrency(extracted.total)}</b></span>}
              </div>
            )}

            {/* Line items table */}
            {lineItems.length > 0 && (
              <div>
                <Label>Satır Kalemleri</Label>
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-bg text-text-secondary">
                      <tr>
                        <th className="px-2 py-1.5 text-left font-medium">Açıklama</th>
                        <th className="px-2 py-1.5 text-right font-medium">Miktar</th>
                        <th className="px-2 py-1.5 text-right font-medium">Birim Fiyat</th>
                        <th className="px-2 py-1.5 text-right font-medium">Tutar</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lineItems.map((li, i) => (
                        <tr key={i} className="border-t border-border">
                          <td className="px-2 py-1.5 text-text-primary">{li.description ?? "—"}</td>
                          <td className="tabular px-2 py-1.5 text-right">{li.quantity ?? "—"}</td>
                          <td className="tabular px-2 py-1.5 text-right">{li.unit_price != null ? formatCurrency(li.unit_price) : "—"}</td>
                          <td className="tabular px-2 py-1.5 text-right">{li.amount != null ? formatCurrency(li.amount) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => navigate(projectId ? `/projects/${projectId}/budget` : "/projects")}>İptal</Button>
              <Button type="button" onClick={save} loading={saving}><CheckCircle2 className="h-4 w-4" /> {destination === "equipment" ? "Ekipman Olarak Kaydet" : destination === "income" ? "Gelir Olarak Kaydet" : "Maliyet Olarak Kaydet"}</Button>
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
