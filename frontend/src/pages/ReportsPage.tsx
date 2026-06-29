import { PageHeader } from "@/components/layout/AppLayout";
import { Card, CardBody, Select, Button } from "@/components/ui";
import { LoadError } from "@/components/EmptyState";
import { useFetch } from "@/hooks/useFetch";
import { api } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Project } from "@/types";
import { FileText, Download } from "lucide-react";
import { useState } from "react";

// CR-048 — each card maps to a real backend report endpoint (blob download).
// `slug` is the Türkçe-slugged base filename; `excel: true` cards (cost, cashflow)
// expose a PDF/Excel format choice (?fmt=xlsx). The others are PDF-only — we never
// send `fmt` for them. `project`/management-pack behaviour stays unchanged.
type ReportDef = { key: string; name: string; desc: string; slug: string; excel: boolean };
const REPORTS: ReportDef[] = [
  { key: "project", name: "Proje Durum Raporu", desc: "Tam finansal özet: KPI'lar, bütçe vs gerçekleşen, nakit akışı, AI uyarıları", slug: "proje-durum-raporu", excel: false },
  { key: "cost", name: "Maliyet Detay Raporu", desc: "Tüm maliyet girişleri, kategori bazında toplamlar", slug: "maliyet-detay-raporu", excel: true },
  { key: "invoice", name: "Hakediş Raporu", desc: "Tüm hakediş faturaları, tahsilat durumu, kesinti özeti", slug: "hakedis-raporu", excel: false },
  { key: "subcontractor", name: "Alt Yüklenici Raporu", desc: "Tüm alt yükleniciler, ödeme durumu, tutulan kesinti", slug: "alt-yuklenici-raporu", excel: false },
  { key: "cashflow", name: "Nakit Akış Raporu", desc: "Aylık nakit akış tablosu (giriş/çıkış/net/kümülatif)", slug: "nakit-akis-raporu", excel: true },
];

// The blob endpoint per report key. cost/cashflow accept ?fmt=pdf|xlsx (default pdf);
// the rest are PDF-only.
const ENDPOINT: Record<string, string> = {
  project: "/reports/project",
  cost: "/reports/cost",
  invoice: "/reports/invoice",
  subcontractor: "/reports/subcontractor",
  cashflow: "/reports/cashflow",
};

type Fmt = "pdf" | "xlsx";

export default function ReportsPage() {
  const { data, loading: projectsLoading, error: projectsError, refetch: refetchProjects } = useFetch<Project[]>("/projects");
  const [projectId, setProjectId] = useState("");
  // Per-(card,format) loading so one button spins without disabling the rest.
  const [busy, setBusy] = useState<string | null>(null);

  // CR-048 — download any of the five reports as a blob. `fmt` only ever travels to
  // the backend for the Excel-capable cards (cost, cashflow); PDF-only reports never
  // receive a `fmt` param. The Supabase JWT is attached by the api request interceptor.
  const download = async (key: string, fmt: Fmt = "pdf") => {
    if (!projectId) {
      toast.error("Lütfen bir proje seçin");
      return;
    }
    const def = REPORTS.find((r) => r.key === key);
    if (!def) return;
    const sendXlsx = def.excel && fmt === "xlsx";
    const ext = sendXlsx ? "xlsx" : "pdf";
    const busyKey = `${key}:${ext}`;
    setBusy(busyKey);
    try {
      const res = await api.get(`${ENDPOINT[key]}/${projectId}`, {
        responseType: "blob",
        // Only cost/cashflow Excel needs a param; PDF is the backend default.
        params: sendXlsx ? { fmt: "xlsx" } : undefined,
      });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${def.slug}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Rapor indirildi");
    } catch (e: any) {
      toast.error(e.message ?? "Rapor oluşturulamadı");
    } finally {
      setBusy(null);
    }
  };

  // CR-003-K: monthly management pack.
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [packLoading, setPackLoading] = useState(false);
  const downloadPack = async () => {
    setPackLoading(true);
    try {
      const res = await api.get("/reports/management-pack", { params: { period }, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "aylik-yonetim-paketi.pdf";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Rapor indirildi");
    } catch (e: any) {
      toast.error(e.message ?? "Rapor oluşturulamadı");
    } finally {
      setPackLoading(false);
    }
  };

  return (
    <div>
      <PageHeader title="Raporlar" />

      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-text-secondary">Aylık Yönetim Paketi</label>
            <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} className="rounded-md border border-border bg-surface px-3 py-2 text-sm" />
          </div>
          <Button loading={packLoading} onClick={downloadPack}>
            <Download className="h-4 w-4" /> Aylık Yönetim Paketi İndir
          </Button>
          <p className="text-xs text-text-secondary">7 sayfalık AI destekli yönetim raporu (oluşturma 15-30 sn sürebilir).</p>
        </CardBody>
      </Card>
      <div className="mb-4 max-w-sm">
        {/* A failed project load must not look like an empty dropdown — show a
            clear error + retry so report selection isn't silently broken. */}
        {projectsError && !projectsLoading ? (
          <LoadError message="Projeler yüklenemedi." onRetry={refetchProjects} />
        ) : (
          <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} disabled={projectsLoading}>
            <option value="">{projectsLoading ? "Projeler yükleniyor…" : "Proje seçin..."}</option>
            {(data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        )}
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {REPORTS.map((r) => (
          <Card key={r.key} className="h-full">
            <CardBody className="flex h-full flex-col">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-navy-50"><FileText className="h-5 w-5 text-primary" /></div>
                <div className="flex-1">
                  <h3 className="font-semibold text-primary">{r.name}</h3>
                  <p className="mt-1 text-xs text-text-secondary">{r.desc}</p>
                  <span className="mt-1 inline-block rounded bg-bg px-1.5 py-0.5 text-[10px] text-text-secondary">{r.excel ? "PDF + Excel" : "PDF"}</span>
                </div>
              </div>
              {/* Excel-capable cards (cost, cashflow) offer a format choice; the rest
                  download as PDF. Each button spins independently while in flight. */}
              {r.excel ? (
                <div className="mt-auto flex gap-2">
                  <Button variant="outline" className="flex-1" loading={busy === `${r.key}:pdf`} disabled={busy !== null && busy !== `${r.key}:pdf`} onClick={() => download(r.key, "pdf")}>
                    <Download className="h-4 w-4" /> PDF
                  </Button>
                  <Button variant="outline" className="flex-1" loading={busy === `${r.key}:xlsx`} disabled={busy !== null && busy !== `${r.key}:xlsx`} onClick={() => download(r.key, "xlsx")}>
                    <Download className="h-4 w-4" /> Excel
                  </Button>
                </div>
              ) : (
                <Button variant="outline" className="mt-auto w-full" loading={busy === `${r.key}:pdf`} disabled={busy !== null && busy !== `${r.key}:pdf`} onClick={() => download(r.key, "pdf")}>
                  <Download className="h-4 w-4" /> İndir
                </Button>
              )}
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  );
}
