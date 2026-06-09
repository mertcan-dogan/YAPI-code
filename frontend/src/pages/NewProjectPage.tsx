import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody, FieldError, Input, Label, Select, Textarea } from "@/components/ui";
import { InfoTooltip } from "@/components/ui/tooltip";
import { COST_CATEGORY_OPTIONS, PROJECT_TYPE_GROUPS } from "@/constants";
import { apiGet, apiPost } from "@/lib/api";
import { toast } from "@/store/toast";
import { formatCurrency, toNumber } from "@/utils/format";
import { cn } from "@/lib/cn";
import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

const STEPS = ["Proje Bilgileri", "Finansal Bilgiler", "Zaman Planı", "Bütçe Dağılımı"];

export default function NewProjectPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prevTypes, setPrevTypes] = useState<{ value: string; label: string }[]>([]);
  const [templates, setTemplates] = useState<{ id: string; name: string; distribution: Record<string, number> }[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [form, setForm] = useState<any>({
    name: "",
    project_code: "",
    project_type: "road",
    custom_project_type: "",
    client_name: "",
    client_contact: "",
    contract_number: "",
    location: "",
    contract_value_try: "",
    contract_value_eur: "",
    eur_try_rate: "",
    retention_pct: "10",
    contingency_pct: "5",
    target_margin_pct: "",
    original_budget_try: "",
    start_date: "",
    planned_end_date: "",
  });
  const [budgets, setBudgets] = useState<Record<string, string>>({});
  // CR-001-D: ad-hoc custom categories added in the wizard.
  const [customCats, setCustomCats] = useState<{ name: string; amount: string }[]>([]);

  const set = (k: string, v: string) => {
    setForm((f: any) => ({ ...f, [k]: v }));
    // Auto-suggest project code from name (Section 11).
    if (k === "name" && !form.project_code) {
      setForm((f: any) => ({ ...f, project_code: v.toUpperCase().replace(/[^A-Z0-9]+/g, "-").slice(0, 20) }));
    }
  };

  // CR-001-A: surface the company's previously used custom types as a group.
  useEffect(() => {
    apiGet<any[]>("/projects")
      .then(({ data }) => {
        const seen = new Map<string, string>();
        for (const p of data ?? []) {
          if (p.project_type === "other" && p.custom_project_type) {
            seen.set(p.custom_project_type.toLowerCase(), p.custom_project_type);
          }
        }
        setPrevTypes(Array.from(seen.values()).map((v) => ({ value: `prev:${v}`, label: v })));
      })
      .catch(() => setPrevTypes([]));
    // CR-003-L: load budget templates.
    apiGet<any[]>("/budget-templates").then(({ data }) => setTemplates(data ?? [])).catch(() => setTemplates([]));
  }, []);

  const applyTemplate = () => {
    const t = templates.find((x) => x.id === selectedTemplate);
    const contract = toNumber(form.original_budget_try || form.contract_value_try);
    if (!t || contract <= 0) {
      toast.error("Şablon uygulamak için önce sözleşme/bütçe değeri girin");
      return;
    }
    const next: Record<string, string> = {};
    for (const [cat, pct] of Object.entries(t.distribution)) {
      next[cat] = String(Math.round((contract * Number(pct)) / 100));
    }
    setBudgets(next);
    toast.success(`"${t.name}" şablonu uygulandı`);
  };

  const budgetTotal =
    Object.values(budgets).reduce((s, v) => s + toNumber(v), 0) +
    customCats.reduce((s, c) => s + toNumber(c.amount), 0);
  const budgetMismatch = budgetTotal > 0 && Math.abs(budgetTotal - toNumber(form.original_budget_try)) > 0.01;

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      // Normalise the type: a "prev:<text>" selection is a reused custom type.
      let projectType = form.project_type;
      let customType: string | null = form.custom_project_type || null;
      if (projectType.startsWith("prev:")) {
        customType = projectType.slice(5);
        projectType = "other";
      }
      if (projectType !== "other") customType = null;
      const payload: any = {
        ...form,
        project_type: projectType,
        custom_project_type: customType,
        contract_value_try: form.contract_value_try,
        original_budget_try: form.original_budget_try || form.contract_value_try,
        contract_value_eur: form.contract_value_eur || null,
        eur_try_rate: form.eur_try_rate || "1.0",
        target_margin_pct: form.target_margin_pct || null,
      };
      const project = await apiPost<{ id: string }>("/projects", payload);
      // Save any per-category budgets entered in step 4.
      for (const [cat, amount] of Object.entries(budgets)) {
        if (toNumber(amount) > 0) {
          await apiPost(`/projects/${project.id}/budget/${cat}`, { original_budget_try: amount }).catch(() => {});
        }
      }
      // CR-001-D: register custom categories at the company level.
      for (const c of customCats) {
        if (c.name.trim()) {
          await apiPost("/custom-categories", { name: c.name.trim() }).catch(() => {});
        }
      }
      toast.success("Proje oluşturuldu");
      navigate(`/projects/${project.id}/dashboard`);
    } catch (e: any) {
      setError(e.message ?? "Proje oluşturulamadı");
      toast.error(e.message ?? "Proje oluşturulamadı");
    } finally {
      setSaving(false);
    }
  };

  const canNext = () => {
    if (step === 0)
      return (
        form.name &&
        form.project_code &&
        form.client_name &&
        (form.project_type !== "other" || form.custom_project_type.trim())
      );
    if (step === 1) return toNumber(form.contract_value_try) > 0;
    if (step === 2) return form.start_date && form.planned_end_date;
    return true;
  };

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Yeni Proje" />
      <div className="mb-6 flex gap-2">
        {STEPS.map((s, i) => (
          <div key={s} className="flex-1">
            <div className={cn("h-1 rounded-full", i <= step ? "bg-primary" : "bg-border")} />
            <span className={cn("mt-1 block text-xs", i === step ? "font-semibold text-primary" : "text-text-secondary")}>{s}</span>
          </div>
        ))}
      </div>

      <Card>
        <CardBody className="space-y-4">
          {step === 0 && (
            <>
              <Field label="Proje Adı" required>
                <Input value={form.name} onChange={(e) => set("name", e.target.value)} />
              </Field>
              <Field label="Proje Kodu" required>
                <Input value={form.project_code} onChange={(e) => set("project_code", e.target.value)} />
              </Field>
              <Field label="Proje Türü" required>
                <Select value={form.project_type} onChange={(e) => set("project_type", e.target.value)}>
                  {PROJECT_TYPE_GROUPS.map((g) => (
                    <optgroup key={g.category} label={g.category}>
                      {g.options.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </optgroup>
                  ))}
                  {prevTypes.length > 0 && (
                    <optgroup label="Şirketinizin Önceki Türleri">
                      {prevTypes.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </optgroup>
                  )}
                </Select>
              </Field>
              {form.project_type === "other" && (
                <Field label="Proje Türünü Belirtin" required>
                  <Input
                    value={form.custom_project_type}
                    maxLength={100}
                    onChange={(e) => set("custom_project_type", e.target.value)}
                    placeholder="Örn. Maden Tesisi"
                    autoFocus
                  />
                </Field>
              )}
              <Field label="İşveren Adı" required>
                <Input value={form.client_name} onChange={(e) => set("client_name", e.target.value)} />
              </Field>
              <Field label="İşveren İrtibat Kişisi">
                <Input value={form.client_contact} onChange={(e) => set("client_contact", e.target.value)} />
              </Field>
              <Field label="Sözleşme Numarası">
                <Input value={form.contract_number} onChange={(e) => set("contract_number", e.target.value)} />
              </Field>
              <Field label="Proje Lokasyonu">
                <Input value={form.location} onChange={(e) => set("location", e.target.value)} />
              </Field>
            </>
          )}

          {step === 1 && (
            <>
              <Field label="Sözleşme Değeri (TRY)" required>
                <Input type="number" value={form.contract_value_try} onChange={(e) => set("contract_value_try", e.target.value)} />
              </Field>
              <Field label="Onaylı Bütçe (TRY)">
                <Input type="number" value={form.original_budget_try} onChange={(e) => set("original_budget_try", e.target.value)} placeholder="Boşsa sözleşme değeri kullanılır" />
              </Field>
              <Field label="Sözleşme Değeri (EUR)">
                <Input type="number" value={form.contract_value_eur} onChange={(e) => set("contract_value_eur", e.target.value)} />
              </Field>
              {form.contract_value_eur && (
                <Field label="EUR/TRY Kuru">
                  <Input type="number" value={form.eur_try_rate} onChange={(e) => set("eur_try_rate", e.target.value)} />
                </Field>
              )}
              <div className="grid grid-cols-3 gap-3">
                <Field label="Hakediş Kesintisi %">
                  <Input type="number" value={form.retention_pct} onChange={(e) => set("retention_pct", e.target.value)} />
                </Field>
                <div>
                  <Label className="flex items-center gap-1">
                    Öngörülemeyen Giderler %
                    <InfoTooltip text="Öngörülemeyen giderler, proje süresince ortaya çıkabilecek beklenmedik maliyetler için ayrılan bütçe payıdır. Türk kamu ihale mevzuatında standart oran %10'dur. Özel projeler için %5 ile %15 arasında belirlenmesi önerilir." />
                  </Label>
                  <Input type="number" value={form.contingency_pct} onChange={(e) => set("contingency_pct", e.target.value)} />
                </div>
                <Field label="Hedef Kar Marjı %">
                  <Input type="number" value={form.target_margin_pct} onChange={(e) => set("target_margin_pct", e.target.value)} />
                </Field>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <Field label="Başlangıç Tarihi" required>
                <Input type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)} />
              </Field>
              <Field label="Planlanan Bitiş Tarihi" required>
                <Input type="date" value={form.planned_end_date} onChange={(e) => set("planned_end_date", e.target.value)} />
              </Field>
            </>
          )}

          {step === 3 && (
            <>
              {templates.length > 0 && (
                <div className="flex items-end gap-2 rounded-md border border-border bg-bg p-3">
                  <div className="flex-1">
                    <Label>Şablondan Yükle</Label>
                    <Select value={selectedTemplate} onChange={(e) => setSelectedTemplate(e.target.value)}>
                      <option value="">Şablon seçin…</option>
                      {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                    </Select>
                  </div>
                  <Button type="button" variant="outline" disabled={!selectedTemplate} onClick={applyTemplate}>Uygula</Button>
                </div>
              )}
              <p className="text-sm text-text-secondary">Kategori bazında bütçe girin (opsiyonel, sonra düzenlenebilir).</p>
              {COST_CATEGORY_OPTIONS.map((c) => (
                <div key={c.value} className="flex items-center gap-3">
                  <span className="flex-1 text-sm">{c.label}</span>
                  <Input
                    type="number"
                    className="w-40"
                    value={budgets[c.value] ?? ""}
                    onChange={(e) => setBudgets((b) => ({ ...b, [c.value]: e.target.value }))}
                  />
                </div>
              ))}

              {/* CR-001-D: custom categories */}
              {customCats.map((c, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    className="flex-1"
                    placeholder="Kategori adı"
                    value={c.name}
                    onChange={(e) => setCustomCats((rows) => rows.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))}
                  />
                  <Input
                    type="number"
                    className="w-40"
                    placeholder="Tutar"
                    value={c.amount}
                    onChange={(e) => setCustomCats((rows) => rows.map((r, j) => (j === i ? { ...r, amount: e.target.value } : r)))}
                  />
                  <button
                    type="button"
                    onClick={() => setCustomCats((rows) => rows.filter((_, j) => j !== i))}
                    className="text-text-secondary hover:text-danger"
                    aria-label="Kategoriyi sil"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                className="w-full border-accent text-accent"
                onClick={() => setCustomCats((rows) => [...rows, { name: "", amount: "" }])}
              >
                <Plus className="h-4 w-4" /> Yeni Kategori Ekle
              </Button>

              <div className={cn("flex justify-between border-t border-border pt-2 text-sm font-semibold", budgetMismatch && "text-accent")}>
                <span>Toplam</span>
                <span>{formatCurrency(budgetTotal)}</span>
              </div>
              {budgetMismatch && (
                <p className="text-xs text-accent">Dikkat: Toplam, onaylı bütçe ({formatCurrency(form.original_budget_try)}) ile eşleşmiyor.</p>
              )}
            </>
          )}

          {error && <FieldError message={error} />}

          <div className="flex justify-between border-t border-border pt-4">
            <Button variant="ghost" onClick={() => (step === 0 ? navigate("/projects") : setStep(step - 1))}>
              {step === 0 ? "İptal" : "Geri"}
            </Button>
            {step < STEPS.length - 1 ? (
              <Button onClick={() => setStep(step + 1)} disabled={!canNext()}>İleri</Button>
            ) : (
              <Button onClick={submit} loading={saving}>Projeyi Oluştur</Button>
            )}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <Label required={required}>{label}</Label>
      {children}
    </div>
  );
}
