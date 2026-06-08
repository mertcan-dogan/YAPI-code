import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button, Card, CardBody } from "@/components/ui";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";
import { useFetch } from "@/hooks/useFetch";
import { apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Reminder } from "@/types";
import { formatCurrency, toNumber } from "@/utils/format";
import { useState } from "react";

function KpiChip({ label, value, bg, border }: { label: string; value: string; bg: string; border: string }) {
  return (
    <div className="rounded-lg border p-3" style={{ backgroundColor: bg, borderColor: border }}>
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="tabular mt-0.5 text-base font-bold text-text-primary">{value}</div>
    </div>
  );
}

const TABS = [
  { key: "all", label: "Tümü" },
  { key: "payable", label: "Ödenecekler" },
  { key: "receivable", label: "Tahsilat" },
] as const;

const TIME_FILTERS = [
  { key: "overdue", label: "Vadesi Geçmiş" },
  { key: "today", label: "Bugün" },
  { key: "7", label: "7 Gün" },
  { key: "30", label: "30 Gün" },
  { key: "60", label: "60 Gün" },
  { key: "all", label: "Tümü" },
];

export default function RemindersPage() {
  const { data, loading, refetch } = useFetch<Reminder[]>("/reminders");
  const [tab, setTab] = useState<"all" | "payable" | "receivable">("all");
  const [time, setTime] = useState("all");

  let items = data ?? [];
  if (tab !== "all") items = items.filter((i) => i.kind === tab);
  items = items.filter((i) => {
    const d = i.days_remaining;
    if (time === "overdue") return d < 0;
    if (time === "today") return d === 0;
    if (time === "7") return d >= 0 && d <= 7;
    if (time === "30") return d >= 0 && d <= 30;
    if (time === "60") return d >= 0 && d <= 60;
    return true;
  });

  const markDone = async (r: Reminder) => {
    try {
      const today = new Date().toISOString().slice(0, 10);
      if (r.kind === "payable") {
        await apiPut(`/projects/${r.project_id}/costs/${r.record_id}`, { payment_status: "paid", date_paid: today });
      } else {
        await apiPut(`/projects/${r.project_id}/invoices/${r.record_id}`, { payment_status: "paid", date_received: today });
      }
      toast.success(r.kind === "payable" ? "Ödendi olarak işaretlendi" : "Tahsil edildi olarak işaretlendi");
      refetch();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  // CR-002-C: summary KPI band computed from all reminders (not the filtered view).
  const all = data ?? [];
  const sumWhere = (pred: (d: number) => boolean) =>
    all.filter((i) => pred(i.days_remaining)).reduce((s, i) => s + toNumber(i.amount_try), 0);
  const overdueTotal = sumWhere((d) => d < 0);
  const todayItems = all.filter((i) => i.days_remaining === 0);
  const todaySum = todayItems.reduce((s, i) => s + toNumber(i.amount_try), 0);
  const weekSum = sumWhere((d) => d > 0 && d <= 7);
  const monthSum = sumWhere((d) => d > 0 && d <= 30);

  return (
    <div>
      <PageHeader title="Hatırlatıcılar" subtitle="Tüm projelerdeki vadesi yaklaşan ve geçmiş ödemeler" />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiChip label="Vadesi Geçmiş Toplam" value={formatCurrency(overdueTotal)} bg="#FEF2F2" border="#EF4444" />
        <KpiChip label="Bugün Vadesi Dolan" value={`${todayItems.length} · ${formatCurrency(todaySum)}`} bg="#FFFBEB" border="#F59E0B" />
        <KpiChip label="Bu Hafta (7 Gün)" value={formatCurrency(weekSum)} bg="#FEFCE8" border="#EAB308" />
        <KpiChip label="Bu Ay (30 Gün)" value={formatCurrency(monthSum)} bg="#EFF6FF" border="#93C5FD" />
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-md border border-border p-0.5">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)} className={cn("rounded px-3 py-1 text-sm", tab === t.key ? "bg-primary text-white" : "text-text-secondary")}>{t.label}</button>
          ))}
        </div>
        <div className="flex gap-1">
          {TIME_FILTERS.map((t) => (
            <button key={t.key} onClick={() => setTime(t.key)} className={cn("rounded-md border px-2.5 py-1 text-xs", time === t.key ? "border-primary bg-primary text-white" : "border-border text-text-secondary")}>{t.label}</button>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-text-secondary">Yükleniyor...</p>
      ) : items.length === 0 ? (
        <Card><CardBody><EmptyState message="Vadesi gelen ödeme bulunmuyor." /></CardBody></Card>
      ) : (
        <div className="space-y-2">
          {items.map((r) => (
            <div key={r.record_id} className="flex items-center gap-4 rounded-lg border border-border p-4" style={{ borderLeft: `4px solid ${r.border_colour}`, backgroundColor: (r as any).bg_colour ?? "#FFFFFF" }}>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-navy-50 px-2 py-0.5 text-xs text-primary-light">{r.project_name}</span>
                  <StatusBadge status={r.status} />
                </div>
                <p className="mt-1 font-semibold text-text-primary">{r.party}</p>
                <p className="text-xs text-text-secondary">{r.description}</p>
              </div>
              <div className="text-right">
                <div className="tabular text-lg font-bold text-primary">{formatCurrency(r.amount_try)}</div>
                <div className={cn("text-xs font-medium", r.days_remaining <= 0 ? "text-danger font-bold" : r.days_remaining <= 7 ? "text-accent" : r.days_remaining <= 30 ? "text-warning" : "text-text-secondary")}>{r.days_label}</div>
              </div>
              <Button variant="outline" onClick={() => markDone(r)}>
                {r.kind === "payable" ? "Ödendi İşaretle" : "Tahsil Edildi İşaretle"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
