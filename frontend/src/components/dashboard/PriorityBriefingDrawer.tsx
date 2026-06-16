import { InsightItem, briefingKey, type BriefingItem } from "@/components/dashboard/InsightItem";
import { SideDrawer } from "@/components/SideDrawer";
import { cn } from "@/lib/cn";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { useState } from "react";

const DONE_KEY = "yapi-briefing-done";

export interface PriorityBriefingDrawerProps {
  open: boolean;
  onClose: () => void;
  briefing: BriefingItem[];
  briefingState: "loading" | "ready" | "error";
  onRefresh: () => void;
}

/**
 * Priority briefing ("Öncelikli İşler") shown from the dashboard toolbar.
 * Holds the AI-generated short action list with per-item done-checkboxes
 * (remembered in localStorage) and a refresh control.
 */
export function PriorityBriefingDrawer({ open, onClose, briefing, briefingState, onRefresh }: PriorityBriefingDrawerProps) {
  const [done, setDone] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(DONE_KEY) || "[]");
    } catch {
      return [];
    }
  });

  const completeItem = (key: string) => {
    if (!window.confirm("Bu işi tamamlandı olarak işaretleyip listeden kaldırmak istediğinize emin misiniz?")) return;
    setDone((d) => {
      const next = Array.from(new Set([...d, key]));
      localStorage.setItem(DONE_KEY, JSON.stringify(next));
      return next;
    });
  };

  const visible = briefing.filter((b) => !done.includes(briefingKey(b)));

  return (
    <SideDrawer open={open} title="Öncelikli İşler" onClose={onClose}>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">Öne çıkan işler</span>
        <button onClick={onRefresh} disabled={briefingState === "loading"} title="Yenile" className="text-text-secondary hover:text-primary disabled:opacity-50" aria-label="Yenile">
          <RefreshCw className={cn("h-3.5 w-3.5", briefingState === "loading" && "animate-spin")} />
        </button>
      </div>
      {briefingState === "loading" ? (
        <p className="py-1 text-xs text-text-secondary">Analiz ediliyor…</p>
      ) : briefingState === "error" ? (
        <p className="py-1 text-xs text-text-secondary">Yapay zeka şu an kullanılamıyor.</p>
      ) : visible.length === 0 ? (
        <div className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-2 text-xs text-success">
          <CheckCircle2 className="h-3.5 w-3.5" /> Öncelikli iş kalmadı.
        </div>
      ) : (
        <div className="divide-y divide-border">
          {visible.map((item) => (
            <InsightItem key={briefingKey(item)} item={item} onComplete={() => completeItem(briefingKey(item))} />
          ))}
        </div>
      )}
    </SideDrawer>
  );
}
