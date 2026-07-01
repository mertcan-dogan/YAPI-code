import { ScopedAgentDock } from "@/components/dashboard/ScopedAgentDock";
import { Badge, Menu, MenuItem } from "@/components/ui";
import type { AIAlert } from "@/types";
import { ArrowRight, ClipboardList, Copy, FileText, MoreVertical, PlusSquare, Tag, Zap, type LucideIcon } from "lucide-react";
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

// CR-029-F §11.1 (fix #5): AI Action Queue. Count rows come from REAL sources —
// approvals split by kind (faturalar / ek işler) + CR-022 finding types; rows
// with 0 are hidden. The two sources without a count endpoint (document-capture
// low-confidence, hazır raporlar) render as navigational links (no fabricated
// number), per founder decision.
interface CountRow {
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

export function AiActionQueue({ alerts, approvalsByKind }: { alerts: AIAlert[]; approvalsByKind: { faturalar: number; ekIsler: number } | null }) {
  const navigate = useNavigate();
  const countRows = useMemo<CountRow[]>(() => {
    const byType = (t: string) => alerts.filter((a) => a.alert_type === t).length;
    const candidates: CountRow[] = [
      { icon: ClipboardList, label: "Onay bekleyen faturalar", count: approvalsByKind?.faturalar ?? 0, priority: "Yüksek", to: "/approvals" },
      { icon: PlusSquare, label: "İncelenecek ek işler", count: approvalsByKind?.ekIsler ?? 0, priority: "Yüksek", to: "/approvals" },
      { icon: Copy, label: "Olası yinelenen faturalar", count: byType("duplicate_cost") + byType("duplicate_invoice"), priority: "Yüksek", to: "/ai-alerts" },
      { icon: Tag, label: "Atanmamış maliyetler", count: byType("unlinked_vendor"), priority: "Orta", to: "/ai-alerts" },
    ];
    return candidates.filter((r) => r.count > 0);
  }, [alerts, approvalsByKind]);

  // Navigational rows — no backend count yet (founder decision: link, no number).
  // "Düşük güvenli çıkarımlar" omitted: extraction confidence isn't persisted, so
  // there's no low-confidence review list/count to link to honestly (yet).
  const navRows: { icon: LucideIcon; label: string; to: string }[] = [
    { icon: FileText, label: "Hazır rapor talepleri", to: "/reports" },
  ];

  const total = countRows.reduce((s, r) => s + r.count, 0);

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
      {countRows.length === 0 && (
        <div className="border-t border-border px-3.5 py-2.5 text-xs text-text-muted">Şu an bekleyen aksiyon yok.</div>
      )}
      {countRows.map((r) => (
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
      ))}
      {navRows.map((r) => (
        <button
          key={r.label}
          onClick={() => navigate(r.to)}
          className="flex w-full items-center gap-2.5 border-t border-border px-3.5 py-2.5 text-left transition-colors hover:bg-surface-hover"
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] border border-border bg-surface-soft text-text-secondary">
            <r.icon className="h-[15px] w-[15px]" />
          </span>
          <span className="flex-1 text-xs">{r.label}</span>
          <ArrowRight className="h-3.5 w-3.5 text-text-faint" />
        </button>
      ))}
      <div className="flex items-center border-t border-border px-3.5 py-2.5">
        <button onClick={() => navigate("/ai-alerts")} className="focus-ring inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
          AI Kuyruğunda tümünü gör <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </RailCard>
  );
}

export function RightRail({ alerts, approvalsByKind }: { alerts: AIAlert[]; approvalsByKind: { faturalar: number; ekIsler: number } | null }) {
  const navigate = useNavigate();
  return (
    <>
      <AiActionQueue alerts={alerts} approvalsByKind={approvalsByKind} />

      {/* §11.2 — CR-011-D: the "Beceriler" half is live (scoped-agent dock);
          CR-012: "Otomasyonlar" now links to the live Automations page. */}
      <RailCard title="AI Beceriler & Otomasyonlar" right={<span className="text-xs text-text-faint">Beceriler</span>}>
        <div className="border-t border-border">
          <ScopedAgentDock />
        </div>
        <button
          onClick={() => navigate("/automations")}
          className="flex w-full items-center gap-2.5 border-t border-border px-3.5 py-2.5 text-left transition-colors hover:bg-surface-hover"
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] border border-border bg-surface-soft text-text-secondary">
            <Zap className="h-[15px] w-[15px]" />
          </span>
          <span className="flex-1">
            <span className="block text-[11px] font-medium text-text-secondary">Otomasyonlar</span>
            <span className="mt-0.5 block text-xs text-text-muted">Belge dosyalama & periyodik özet</span>
          </span>
          <ArrowRight className="h-3.5 w-3.5 text-text-faint" />
        </button>
      </RailCard>

      {/* §11.3 Phase-2 (new collaboration backend). */}
      <RailCard title="Ekip Akışı" right={<span className="text-xs text-text-faint">Tümünü gör</span>}>
        <ComingSoon />
      </RailCard>
    </>
  );
}
