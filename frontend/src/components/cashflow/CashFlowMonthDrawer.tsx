import { SideDrawer } from "@/components/SideDrawer";
import { COST_CATEGORIES } from "@/constants";
import { apiGet } from "@/lib/api";
import { formatCurrency, formatDate, toNumber } from "@/utils/format";
import { useEffect, useState } from "react";

interface CostRow { id: string; cost_category: string; supplier_name?: string | null; description?: string | null; total_with_vat_try: string; amount_paid_try?: string; remaining_try: string; payment_due_date?: string | null; payment_status: string; }
interface InvRow { id: string; invoice_number: string; hakkedis_period?: string | null; outstanding_try: string; net_due_try: string; due_date: string; payment_status: string; }
interface DetailResp { month: string; costs: CostRow[]; invoices: InvRow[]; total_out_try: string; total_in_try: string; net_try: string; }

// CR-004-M: monthly cash-flow drill-down — planned outflows & expected inflows.
export function CashFlowMonthDrawer({
  open,
  month,
  projectId,
  cumulative,
  onClose,
}: {
  open: boolean;
  month: string | null;
  projectId: string;
  cumulative?: string;
  onClose: () => void;
}) {
  const [costs, setCosts] = useState<CostRow[]>([]);
  const [invoices, setInvoices] = useState<InvRow[]>([]);
  const [totals, setTotals] = useState<{ out: number; in: number; net: number }>({ out: 0, in: 0, net: 0 });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !month) return;
    setLoading(true);
    // CR-005-D: dedicated detail endpoint with server-side month filtering. The
    // previous client-side approach requested per_page=500 (cap is 100), so the
    // 422 rejected the whole Promise.all and both lists showed "(0)".
    apiGet<DetailResp>(`/projects/${projectId}/cashflow/detail`, { month })
      .then((r) => {
        const d = r.data;
        setCosts(d?.costs ?? []);
        setInvoices(d?.invoices ?? []);
        setTotals({ out: toNumber(d?.total_out_try), in: toNumber(d?.total_in_try), net: toNumber(d?.net_try) });
      })
      .catch(() => { setCosts([]); setInvoices([]); setTotals({ out: 0, in: 0, net: 0 }); })
      .finally(() => setLoading(false));
  }, [open, month, projectId]);

  const outTotal = totals.out;
  const inTotal = totals.in;
  const net = totals.net;

  return (
    <SideDrawer open={open} onClose={onClose} title={`${month ?? ""} — Nakit Akışı Detayı`}>
      {loading ? (
        <p className="text-sm text-text-secondary">Yükleniyor…</p>
      ) : (
        <div className="space-y-5">
          <section>
            <p className="mb-2 text-xs font-semibold text-danger">Gider Tahminleri ({costs.length})</p>
            {costs.length === 0 ? <p className="text-sm text-text-secondary">Bu ay vadesi gelen gider yok.</p> : (
              <div className="space-y-1.5">
                {costs.map((r) => (
                  <div key={r.id} className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
                    <div>
                      <div className="font-medium">{r.supplier_name || COST_CATEGORIES[r.cost_category] || r.cost_category}</div>
                      <div className="text-xs text-text-secondary">{formatDate(r.payment_due_date)}</div>
                    </div>
                    <span className="tabular text-danger">{formatCurrency(r.remaining_try)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <p className="mb-2 text-xs font-semibold text-success">Beklenen Tahsilatlar ({invoices.length})</p>
            {invoices.length === 0 ? <p className="text-sm text-text-secondary">Bu ay beklenen tahsilat yok.</p> : (
              <div className="space-y-1.5">
                {invoices.map((r) => (
                  <div key={r.id} className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
                    <div>
                      <div className="font-medium">{r.hakkedis_period || r.invoice_number}</div>
                      <div className="text-xs text-text-secondary">{formatDate(r.due_date)}</div>
                    </div>
                    <span className="tabular text-success">{formatCurrency(r.outstanding_try || r.net_due_try)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="space-y-1 rounded-md bg-bg p-3 text-sm">
            <Row label="Toplam Gider" value={formatCurrency(outTotal)} />
            <Row label="Toplam Tahsilat" value={formatCurrency(inTotal)} />
            <Row label="Net Fark" value={formatCurrency(net)} bold colour={net < 0 ? "#EF4444" : "#10B981"} />
            {cumulative !== undefined && <Row label="Kümülatif Etki" value={formatCurrency(cumulative)} colour={toNumber(cumulative) < 0 ? "#EF4444" : undefined} />}
          </section>
        </div>
      )}
    </SideDrawer>
  );
}

function Row({ label, value, bold, colour }: { label: string; value: string; bold?: boolean; colour?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className={bold ? "font-semibold" : "text-text-secondary"}>{label}</span>
      <span className={`tabular ${bold ? "font-bold" : ""}`} style={{ color: colour ?? "var(--color-text-primary)" }}>{value}</span>
    </div>
  );
}
