import { EmptyState } from "@/components/EmptyState";
import { Button, Card, CardBody } from "@/components/ui";
import { apiPost } from "@/lib/api";
import { toast } from "@/store/toast";
import type { AIAlert, AssuranceScanSummary } from "@/types";
import { ShieldCheck, Search } from "lucide-react";
import { useState } from "react";
import { AlertCard, findingDeepLink } from "./AlertCard";

const SEV_ORDER: Array<AIAlert["severity"]> = ["high", "medium", "low"];
const SEV_LABEL: Record<string, string> = { high: "Yüksek", medium: "Orta", low: "Düşük" };

interface Props {
  findings: AIAlert[];
  onDismiss: (id: string) => void;
  onFeedback: (id: string, feedback: string) => void;
  onRefetch: () => void;
}

/**
 * CR-022-C — "Finans Güvence": runs the read-only assurance scan and lists the
 * anomaly findings with reasoning + deep-link, reusing dismiss/feedback. The
 * banner shows YAPI's honest, real-numbers "kayıt tarandı / bulgu" stat.
 */
export function FinansGuvence({ findings, onDismiss, onFeedback, onRefetch }: Props) {
  const [scanning, setScanning] = useState(false);
  const [summary, setSummary] = useState<AssuranceScanSummary | null>(null);

  const runScan = async () => {
    setScanning(true);
    try {
      const res = await apiPost<AssuranceScanSummary>("/ai/assurance/scan");
      setSummary(res);
      onRefetch();
      toast.success(`Tarama tamamlandı — ${res.total_found} bulgu`);
    } catch (e: any) {
      toast.error(e?.message ?? "Tarama başarısız oldu");
    } finally {
      setScanning(false);
    }
  };

  const scannedTotal = summary ? summary.scanned.cost_entries + summary.scanned.client_invoices : null;

  return (
    <div className="space-y-3">
      {/* Scan summary banner — YAPI's honest answer to "190m errors caught". */}
      <Card>
        <CardBody>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-navy-50 text-brand">
                <ShieldCheck className="h-5 w-5" />
              </span>
              <div>
                <p className="text-sm font-semibold text-primary">Finans Güvence</p>
                <p className="text-xs text-text-secondary">
                  {scannedTotal !== null
                    ? `Son taramada ${scannedTotal.toLocaleString("tr-TR")} kayıt tarandı, ${summary!.total_found} bulgu (${summary!.created} yeni).`
                    : "Kayıtlarınızı olağandışı durumlar için tarayın — yalnızca okur, hiçbir veriyi değiştirmez."}
                </p>
              </div>
            </div>
            <Button variant="outline" loading={scanning} onClick={runScan}>
              <Search className="h-4 w-4" /> Şimdi tara
            </Button>
          </div>
        </CardBody>
      </Card>

      {findings.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState message="Tebrikler — bulgu yok." />
          </CardBody>
        </Card>
      ) : (
        SEV_ORDER.filter((sev) => findings.some((f) => f.severity === sev)).map((sev) => (
          <div key={sev} className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
              {SEV_LABEL[sev]} ({findings.filter((f) => f.severity === sev).length})
            </h3>
            {findings
              .filter((f) => f.severity === sev)
              .map((f) => (
                <AlertCard
                  key={f.id}
                  alert={f}
                  onDismiss={onDismiss}
                  onFeedback={onFeedback}
                  deepLinkHref={findingDeepLink(f)}
                />
              ))}
          </div>
        ))
      )}
    </div>
  );
}
