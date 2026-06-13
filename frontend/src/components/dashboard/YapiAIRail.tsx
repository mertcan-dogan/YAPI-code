import { InsightItem, briefingKey, type BriefingItem } from "@/components/dashboard/InsightItem";
import { SideDrawer } from "@/components/SideDrawer";
import { AIDisclaimer } from "@/components/ui";
import { apiPost } from "@/lib/api";
import { cn } from "@/lib/cn";
import { CheckCircle2, ChevronRight, Loader2, RefreshCw, Send, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const DONE_KEY = "yapi-briefing-done";

interface ChatMsg {
  role: "user" | "ai";
  text: string;
}

interface RailProps {
  briefing: BriefingItem[];
  briefingState: "loading" | "ready" | "error";
  onRefresh: () => void;
  onGoToTasks: () => void;
}

function RailContent({ onClose, hideHeader, briefing, briefingState, onRefresh, onGoToTasks }: RailProps & { onClose?: () => void; hideHeader?: boolean }) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [done, setDone] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(DONE_KEY) || "[]");
    } catch {
      return [];
    }
  });
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, asking]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || asking) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: q }]);
    setAsking(true);
    try {
      const res = await apiPost<{ answer: string; generated_at: string }>("/ai/assistant", { question: q, project_id: null });
      setMessages((m) => [...m, { role: "ai", text: res.answer }]);
    } catch (e: any) {
      setMessages((m) => [...m, { role: "ai", text: e?.message ?? "AI şu an kullanılamıyor." }]);
    } finally {
      setAsking(false);
    }
  };

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
    <div className="flex h-full flex-col">
      {!hideHeader && (
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 text-white">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold text-primary">Yapı AI</span>
            <span className="rounded-full bg-navy-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-brand">Beta</span>
          </div>
          {onClose && (
            <button onClick={onClose} className="text-text-secondary hover:text-primary" aria-label="Yapı AI panelini kapat">
              <ChevronRight className="h-4 w-4" />
            </button>
          )}
        </div>
      )}

      {/* Short, actionable priority list with done-checkboxes */}
      {(briefingState !== "ready" || visible.length > 0) && (
        <div className="border-b border-border px-4 py-2.5">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-text-secondary">Öncelikli İşler</span>
            <button onClick={onRefresh} disabled={briefingState === "loading"} title="Yenile" className="text-text-secondary hover:text-primary disabled:opacity-50" aria-label="Yenile">
              <RefreshCw className={cn("h-3.5 w-3.5", briefingState === "loading" && "animate-spin")} />
            </button>
          </div>
          {briefingState === "loading" ? (
            <p className="py-1 text-xs text-text-secondary">Analiz ediliyor…</p>
          ) : briefingState === "error" ? (
            <p className="py-1 text-xs text-text-secondary">Yapay zeka şu an kullanılamıyor.</p>
          ) : (
            <div className="max-h-44 divide-y divide-border overflow-y-auto">
              {visible.slice(0, 6).map((item) => (
                <InsightItem key={briefingKey(item)} item={item} onComplete={() => completeItem(briefingKey(item))} />
              ))}
            </div>
          )}
        </div>
      )}
      {briefingState === "ready" && visible.length === 0 && (
        <div className="flex items-center gap-2 border-b border-border bg-green-50 px-4 py-2 text-xs text-success">
          <CheckCircle2 className="h-3.5 w-3.5" /> Öncelikli iş kalmadı.
        </div>
      )}

      {/* Large, modern chat */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand to-brand-2 text-white shadow-sm">
              <Sparkles className="h-6 w-6" />
            </span>
            <p className="text-sm font-semibold text-primary">Yapı AI'ya sorun</p>
            <p className="mt-1 max-w-[240px] text-xs text-text-secondary">Projeleriniz, marjlar, hakedişler ve nakit akışı hakkında her şeyi sorun — yanıtlar şirket verilerinize dayanır.</p>
          </div>
        ) : (
          <>
            {messages.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand px-3 py-2 text-[13px] text-white">{m.text}</div>
                </div>
              ) : (
                <div key={i} className="flex items-start gap-2">
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 text-white">
                    <Sparkles className="h-3.5 w-3.5" />
                  </span>
                  <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-bg px-3 py-2 text-[13px] leading-snug text-text-primary">
                    <p className="whitespace-pre-wrap">{m.text}</p>
                  </div>
                </div>
              )
            )}
            {asking && (
              <div className="flex items-center gap-2 text-[13px] text-text-secondary">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Yanıtlanıyor…
              </div>
            )}
            <AIDisclaimer short />
          </>
        )}
      </div>

      <div className="border-t border-border p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          <div className="flex items-end gap-2 rounded-xl border border-border bg-surface px-3 py-1.5 focus-within:border-brand">
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Yapı AI'ya bir şey sorun…" className="flex-1 bg-transparent py-1.5 text-sm outline-none" />
            <button type="submit" disabled={!input.trim() || asking} className="mb-0.5 flex h-7 w-7 items-center justify-center rounded-lg bg-brand text-white disabled:opacity-40" aria-label="Gönder">
              <Send className="h-3.5 w-3.5" />
            </button>
          </div>
        </form>
        <button onClick={onGoToTasks} className="mt-2 w-full text-center text-xs font-medium text-brand hover:underline">
          Görevlerime git →
        </button>
      </div>
    </div>
  );
}

/**
 * Responsive wrapper for the Yapı AI rail:
 *  - xl+: a fixed right column, collapsible to a slim reopen tab.
 *  - below xl: a floating toggle that opens the rail in a SideDrawer.
 */
export function YapiAIRail(props: RailProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <>
      {collapsed ? (
        <button
          onClick={() => setCollapsed(false)}
          className="sticky top-6 hidden h-fit shrink-0 items-center gap-2 self-start rounded-l-xl border border-r-0 border-border bg-surface px-2 py-3 text-brand shadow-sm xl:flex"
          aria-label="Yapı AI panelini aç"
        >
          <Sparkles className="h-4 w-4" />
        </button>
      ) : (
        <aside className="sticky top-6 hidden h-[calc(100vh-7rem)] w-[268px] shrink-0 flex-col self-start overflow-hidden rounded-xl border border-border bg-surface shadow-sm xl:flex">
          <RailContent {...props} onClose={() => setCollapsed(true)} />
        </aside>
      )}

      <button
        onClick={() => setDrawerOpen(true)}
        className="fixed bottom-20 right-4 z-30 flex items-center gap-2 rounded-full bg-gradient-to-br from-brand to-brand-2 px-4 py-3 text-sm font-medium text-white shadow-lg xl:hidden"
        aria-label="Yapı AI"
      >
        <Sparkles className="h-4 w-4" /> Yapı AI
      </button>
      <div className="xl:hidden">
        <SideDrawer open={drawerOpen} title="Yapı AI" onClose={() => setDrawerOpen(false)}>
          <RailContent {...props} hideHeader />
        </SideDrawer>
      </div>
    </>
  );
}
