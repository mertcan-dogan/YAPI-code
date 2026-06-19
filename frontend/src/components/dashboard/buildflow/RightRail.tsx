import { Badge, Menu, MenuItem } from "@/components/ui";
import type { AIAlert } from "@/types";
import { ArrowRight, ClipboardList, Coins, Copy, MoreVertical, Percent, Tag, TrendingUp, type LucideIcon } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

const SOON = "Bu özellik yakında tüm kullanıcılara sunulacak.";

function RailCard({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-card border border-border bg-surface shadow-card">
      <div className="flex items-center gap-2 px-3.5 py-3">
        <span className="text-[13px] font-semibold">{title}</span>
        <div className="ml-auto flex items-center gap-2">{right}</div>
      </div>
      {children}
    </div>
  );
}

function ComingSoon() {
  return (
    <div className="px-4 py-8 text-center text-xs text-text-muted">{SOON}</div>
  );
}

// CR-029-F §11.1: AI Action Queue — rows derived from REAL sources (approvals +
// CR-022 assurance finding types). Counts are real; rows with 0 are hidden. (The
// mockup's document-capture/variations/reports rows await count endpoints — wired
// when those land; nothing fabricated.)
interface QueueRow {
  icon: LucideIcon;
  label: string;
  count: number;
  priority: "Yüksek" | "Orta" | "Düşük";
  to: string;
}

const PRIORITY_VARIANT: Record<string, "danger" | "warning" | "success"> = {
  Yüksek: "danger",
  Orta: "warning",
  Düşük: "success",
};

export function AiActionQueue({ alerts, approvalsCount }: { alerts: AIAlert[]; approvalsCount: number | null }) {
  const navigate = useNavigate();
  const rows = useMemo<QueueRow[]>(() => {
    const byType = (t: string) => alerts.filter((a) => a.alert_type === t).length;
    const candidates: QueueRow[] = [
      { icon: ClipboardList, label: "Onay bekleyenler", count: approvalsCount ?? 0, priority: "Yüksek", to: "/approvals" },
      { icon: Copy, label: "Olası yinelenen faturalar", count: byType("duplicate_cost") + byType("duplicate_invoice"), priority: "Yüksek", to: "/ai-alerts" },
      { icon: Percent, label: "KDV / tutar tutarsızlıkları", count: byType("kdv_mismatch"), priority: "Yüksek", to: "/ai-alerts" },
      { icon: Tag, label: "Atanmamış maliyetler", count: byType("unlinked_vendor"), priority: "Orta", to: "/ai-alerts" },
      { icon: TrendingUp, label: "Olağandışı maliyetler", count: byType("cost_outlier"), priority: "Orta", to: "/ai-alerts" },
      { icon: Coins, label: "Eksik kur (USD) bilgisi", count: byType("missing_fx"), priority: "Düşük", to: "/ai-alerts" },
    ];
    return candidates.filter((r) => r.count > 0);
  }, [alerts, approvalsCount]);

  const total = rows.reduce((s, r) => s + r.count, 0);

  return (
    <RailCard
      title="AI Aksiyon Kuyruğu"
      right={
        <>
          {total > 0 && <Badge variant="info" className="bg-brand text-white">{total}</Badge>}
          <Menu align="right" triggerLabel="Kuyruk menüsü" trigger={<MoreVertical className="h-[15px] w-[15px] text-text-faint" />}>
            {(close) => <MenuItem onClick={() => { close(); navigate("/ai-alerts"); }}>Tümünü gör</MenuItem>}
          </Menu>
        </>
      }
    >
      {rows.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-text-muted">Bekleyen aksiyon yok. 👍</div>
      ) : (
        rows.map((r) => (
          <button
            key={r.label}
            onClick={() => navigate(r.to)}
            className="flex w-full items-center gap-2.5 border-t border-border px-3.5 py-2.5 text-left transition-colors hover:bg-surface-hover"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] border border-border bg-surface-soft text-text-secondary">
              <r.icon className="h-[15px] w-[15px]" />
            </span>
            <span className="flex-1 text-xs">{r.label}</span>
            <span className="tabular text-xs font-semibold">{r.count}</span>
            <Badge variant={PRIORITY_VARIANT[r.priority]}>{r.priority}</Badge>
          </button>
        ))
      )}
      <div className="flex items-center border-t border-border px-3.5 py-2.5">
        <button onClick={() => navigate("/ai-alerts")} className="focus-ring inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
          AI Kuyruğunda tümünü gör <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </RailCard>
  );
}

export function RightRail({ alerts, approvalsCount }: { alerts: AIAlert[]; approvalsCount: number | null }) {
  return (
    <>
      <AiActionQueue alerts={alerts} approvalsCount={approvalsCount} />

      {/* §11.2 Phase-2 (CR-011/012): real grid lands when the engines ship. */}
      <RailCard title="AI Beceriler & Otomasyonlar" right={<span className="text-xs text-text-faint">Yönet</span>}>
        <ComingSoon />
      </RailCard>

      {/* §11.3 Phase-2 (new collaboration backend). */}
      <RailCard title="Ekip Akışı" right={<span className="text-xs text-text-faint">Tümünü gör</span>}>
        <ComingSoon />
      </RailCard>
    </>
  );
}
