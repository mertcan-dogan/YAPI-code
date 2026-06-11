import * as React from "react";
import { useNavigate } from "react-router-dom";
import { Bell, Clock, TrendingDown, Wallet, CheckCheck, X } from "lucide-react";

import { apiGet, apiPut } from "@/lib/api";
import { cn } from "@/lib/cn";

type Notification = {
  id: string;
  title: string;
  body: string | null;
  type: string;
  severity: "high" | "medium" | "low";
  is_read: boolean;
  link: string | null;
  created_at: string | null;
};

const BORDER_BY_SEVERITY: Record<string, string> = {
  high: "border-l-danger",
  medium: "border-l-accent",
  low: "border-l-primary-light",
};

function iconFor(type: string) {
  if (type === "overdue_payment") return Clock;
  if (type === "margin_warning") return TrendingDown;
  return Wallet;
}

// "2 saat önce" tarzı göreli zaman.
function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "az önce";
  if (mins < 60) return `${mins} dakika önce`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} saat önce`;
  const days = Math.floor(hours / 24);
  return `${days} gün önce`;
}

export function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const [count, setCount] = React.useState(0);
  const [items, setItems] = React.useState<Notification[]>([]);
  const [loading, setLoading] = React.useState(false);

  const loadCount = React.useCallback(async () => {
    try {
      const { data } = await apiGet<{ count: number }>("/notifications/unread-count");
      setCount(data.count);
    } catch {
      /* sessizce yoksay — zil sayacı kritik değil */
    }
  }, []);

  const loadList = React.useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiGet<Notification[]>("/notifications");
      setItems(data);
    } finally {
      setLoading(false);
    }
  }, []);

  // 30 saniyede bir okunmamış sayısını yokla.
  React.useEffect(() => {
    loadCount();
    const id = window.setInterval(loadCount, 30000);
    return () => window.clearInterval(id);
  }, [loadCount]);

  const openPanel = () => {
    setOpen(true);
    loadList();
  };

  const markRead = async (n: Notification) => {
    if (!n.is_read) {
      try {
        await apiPut(`/notifications/${n.id}/read`);
        setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)));
        setCount((c) => Math.max(0, c - 1));
      } catch {
        /* yoksay */
      }
    }
    if (n.link) {
      setOpen(false);
      navigate(n.link);
    }
  };

  const markAll = async () => {
    try {
      await apiPut("/notifications/read-all");
      setItems((prev) => prev.map((x) => ({ ...x, is_read: true })));
      setCount(0);
    } catch {
      /* yoksay */
    }
  };

  const badge = count > 9 ? "9+" : String(count);

  return (
    <>
      <button
        onClick={openPanel}
        className="relative text-text-secondary hover:text-primary"
        aria-label="Bildirimler"
      >
        <Bell className="h-5 w-5" />
        {count > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
            {badge}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40 bg-black/20" onClick={() => setOpen(false)} />
          <aside className="fixed right-0 top-0 z-50 flex h-full w-[480px] max-w-[90vw] flex-col border-l border-border bg-surface shadow-xl">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-base font-bold text-primary">Bildirimler</h2>
              <div className="flex items-center gap-3">
                <button
                  onClick={markAll}
                  className="flex items-center gap-1 text-xs font-medium text-primary-light hover:underline"
                >
                  <CheckCheck className="h-3.5 w-3.5" /> Tümünü Okundu İşaretle
                </button>
                <button onClick={() => setOpen(false)} aria-label="Kapat" className="text-text-secondary hover:text-primary">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {loading && <div className="p-6 text-center text-sm text-text-secondary">Yükleniyor…</div>}
              {!loading && items.length === 0 && (
                <div className="flex flex-col items-center gap-2 p-10 text-center text-text-secondary">
                  <Bell className="h-8 w-8 opacity-40" />
                  <span className="text-sm">Yeni bildirim yok</span>
                </div>
              )}
              {!loading &&
                items.map((n) => {
                  const Icon = iconFor(n.type);
                  return (
                    <button
                      key={n.id}
                      onClick={() => markRead(n)}
                      className={cn(
                        "flex w-full items-start gap-3 border-b border-l-4 border-border px-4 py-3 text-left transition-colors hover:bg-bg",
                        BORDER_BY_SEVERITY[n.severity] ?? "border-l-border",
                        !n.is_read && "bg-[#EFF6FF]"
                      )}
                    >
                      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-text-primary">{n.title}</p>
                        {n.body && <p className="mt-0.5 line-clamp-2 text-xs text-text-secondary">{n.body}</p>}
                        <p className="mt-1 text-[11px] text-text-secondary">{relativeTime(n.created_at)}</p>
                      </div>
                      {!n.is_read && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-primary-light" />}
                    </button>
                  );
                })}
            </div>
          </aside>
        </>
      )}
    </>
  );
}
