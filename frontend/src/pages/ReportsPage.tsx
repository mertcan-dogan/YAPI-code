import { PageHeader } from "@/components/layout/AppLayout";
import { Card, CardBody, Select, Button } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { api } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Project } from "@/types";
import { FileText, Download } from "lucide-react";
import { useState } from "react";

const REPORTS = [
  { key: "project", name: "Proje Durum Raporu", desc: "Tam finansal özet: KPI'lar, bütçe vs gerçekleşen, nakit akışı, AI uyarıları", formats: "PDF" },
  { key: "cost", name: "Maliyet Detay Raporu", desc: "Tüm maliyet girişleri, kategori bazında toplamlar", formats: "PDF + Excel" },
  { key: "invoice", name: "Hakediş Raporu", desc: "Tüm hakediş faturaları, tahsilat durumu, kesinti özeti", formats: "PDF" },
  { key: "subcontractor", name: "Alt Yüklenici Raporu", desc: "Tüm alt yükleniciler, ödeme durumu, tutulan kesinti", formats: "PDF" },
  { key: "cashflow", name: "Nakit Akış Raporu", desc: "18 aylık nakit akış tablosu", formats: "PDF + Excel" },
];

export default function ReportsPage() {
  const { data } = useFetch<Project[]>("/projects");
  const [projectId, setProjectId] = useState("");

  const download = async (key: string) => {
    if (!projectId) {
      toast.error("Lütfen bir proje seçin");
      return;
    }
    if (key !== "project") {
      toast.info("Bu rapor türü yakında eklenecek");
      return;
    }
    try {
      const res = await api.get(`/reports/project/${projectId}`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `proje-durum-raporu.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Rapor indirildi");
    } catch (e: any) {
      toast.error(e.message ?? "Rapor oluşturulamadı");
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
        <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">Proje seçin...</option>
          {(data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
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
                  <span className="mt-1 inline-block rounded bg-bg px-1.5 py-0.5 text-[10px] text-text-secondary">{r.formats}</span>
                </div>
              </div>
              <Button variant="outline" className="mt-auto w-full" onClick={() => download(r.key)}>
                <Download className="h-4 w-4" /> İndir
              </Button>
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  );
}
