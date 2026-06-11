import { Button, Modal } from "@/components/ui";
import { apiGet, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import { formatCurrency, formatPct, toNumber } from "@/utils/format";
import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";

interface ReminderItem {
  kind: "payable" | "receivable";
  project_id: string;
  project_name: string;
  party: string;
  description: string;
  amount_try: string;
  net_due_try?: string;
  due_date: string;
  days_remaining: number;
  record_id: string;
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

// CR-004-D: clickable "Vadesi Geçmiş Ödemeler" KPI -> rich detail modal.
export function OverduePaymentsModal({
  open,
  onClose,
  onChanged,
  onGoToReminders,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
  onGoToReminders: () => void;
}) {
  const [items, setItems] = useState<ReminderItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    apiGet<ReminderItem[]>("/reminders")
      .then((r) => setItems(r.data.filter((i) => i.days_remaining < 0)))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open) load();
  }, [open]);

  const total = items.reduce((s, i) => s + toNumber(i.amount_try), 0);

  // Darkest red for the most overdue; lighter for the rest.
  const borderColour = (days: number) => {
    const overdue = Math.abs(days);
    if (overdue >= 30) return "#B91C1C";
    if (overdue >= 14) return "#EF4444";
    return "#FCA5A5";
  };

  const markDone = async (item: ReminderItem) => {
    setBusyId(item.record_id);
    try {
      if (item.kind === "payable") {
        await apiPut(`/projects/${item.project_id}/costs/${item.record_id}`, { date_paid: todayISO() });
        toast.success("Ödeme yapıldı olarak işaretlendi");
      } else {
        await apiPut(`/projects/${item.project_id}/invoices/${item.record_id}`, {
          date_received: todayISO(),
          amount_received_try: item.net_due_try ?? item.amount_try,
        });
        toast.success("Tahsilat kaydedildi");
      }
      setItems((prev) => prev.filter((i) => i.record_id !== item.record_id));
      onChanged();
    } catch (e: any) {
      toast.error(e.message ?? "İşlem başarısız");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={
        <span>
          Vadesi Geçmiş Ödemeler — {items.length} Adet
          <span className="ml-2 text-sm font-normal text-text-secondary">Toplam: {formatCurrency(total)}</span>
        </span>
      }
      footer={
        <Button variant="ghost" onClick={onGoToReminders}>
          Hatırlatıcılara Git <ArrowRight className="h-4 w-4" />
        </Button>
      }
    >
      {loading ? (
        <p className="py-6 text-center text-sm text-text-secondary">Yükleniyor…</p>
      ) : items.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-secondary">Vadesi geçmiş ödeme bulunmuyor.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-text-secondary">
                <th className="px-2 py-2">Proje</th>
                <th className="px-2 py-2">Taraf</th>
                <th className="px-2 py-2">Açıklama</th>
                <th className="px-2 py-2 text-right">Tutar</th>
                <th className="px-2 py-2 text-right">Gecikme</th>
                <th className="px-2 py-2 text-right">İşlem</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr
                  key={i.record_id}
                  className="border-b border-border"
                  style={{ borderLeft: `4px solid ${borderColour(i.days_remaining)}` }}
                >
                  <td className="px-2 py-2">{i.project_name}</td>
                  <td className="px-2 py-2">{i.party}</td>
                  <td className="px-2 py-2">{i.description}</td>
                  <td className="px-2 py-2 text-right tabular">{formatCurrency(i.amount_try)}</td>
                  <td className="px-2 py-2 text-right tabular text-danger">{Math.abs(i.days_remaining)} gün</td>
                  <td className="px-2 py-2 text-right">
                    <Button
                      variant="outline"
                      className="px-2 py-1 text-xs"
                      loading={busyId === i.record_id}
                      onClick={() => markDone(i)}
                    >
                      {i.kind === "payable" ? "Ödendi İşaretle" : "Tahsil Edildi"}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

// CR-004-D: "Ağırlıklı Ort. Kar Marjı" KPI -> lowest-margin projects list.
export function LowMarginModal({
  open,
  onClose,
  projects,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  projects: any[];
  onSelect: (id: string) => void;
}) {
  const sorted = [...projects].sort((a, b) => toNumber(a.margin_pct) - toNumber(b.margin_pct));

  return (
    <Modal open={open} onClose={onClose} title="En Düşük Marjlı Projeler">
      {sorted.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-secondary">Proje bulunmuyor.</p>
      ) : (
        <div className="divide-y divide-border">
          {sorted.map((p) => {
            const m = toNumber(p.margin_pct);
            const colour = m < 5 ? "text-danger" : m < 10 ? "text-accent" : "text-success";
            return (
              <button
                key={p.id}
                onClick={() => onSelect(p.id)}
                className="flex w-full items-center justify-between py-3 text-left hover:bg-bg"
              >
                <div>
                  <div className="font-medium text-primary">{p.name}</div>
                  <div className="text-xs text-text-secondary">{p.client_name}</div>
                </div>
                <span className={`text-sm font-semibold ${colour}`}>{formatPct(p.margin_pct)}</span>
              </button>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
