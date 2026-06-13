import { InsightItem, type BriefingItem } from "@/components/dashboard/InsightItem";
import { SideDrawer } from "@/components/SideDrawer";
import { AIDisclaimer } from "@/components/ui";
import { apiPost } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/utils/format";
import { CheckCircle2, ChevronRight, Info, ListChecks, Loader2, RefreshCw, Send, Sparkles } from "lucide-react";
import { useState } from "react";

const SUGGESTIONS = [
  "Marjı en düşük proje hangisi ve neden?",
  "Bu ay tahsil edilecek hakedişler neler?",
];

interface ChatMsg {
  role: "user" | "ai";
  text: string;
}

interface RailProps {
  briefing: BriefingItem[];
  briefingState: "loading" | "ready" | "error";
  generatedAt: string | null;
  onRefresh: () => void;
  onGoToTasks: () => void;
}

function RailContent({ onClose, hideHeader, briefing, briefingState, generatedAt, onRefresh, onGoToTasks }: RailProps & { onClose?: () => void; hideHeader?: boolean }) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);

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

  const recommendations = briefing.filter((b) => b.impact_try != null && b.impact_try !== 0);
  const actions = briefing.filter((b) => !(b.impact_try != null && b.impact_try !== 0));

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

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {/* Chat */}
        {messages.length === 0 ? (
          <div className="space-y-1.5">
            <p className="text-xs text-text-secondary">Projeleriniz hakkında soru sorun:</p>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => ask(s)}
                className="flex w-full items-start gap-2 rounded-lg border border-border bg-bg px-3 py-2 text-left text-[13px] text-text-primary transition-colors hover:border-brand hover:bg-navy-50"
              >
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
                <span>{s}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {messages.map((m, i) => (
              <div key={i} className={cn("rounded-lg px-3 py-2 text-[13px]", m.role === "user" ? "bg-navy-50 text-primary" : "bg-bg text-text-primary")}>
                <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-text-secondary">{m.role === "user" ? "Siz" : "Yapı AI"}</span>
                <p className="whitespace-pre-wrap leading-snug">{m.text}</p>
              </div>
            ))}
            {asking && (
              <div className="flex items-center gap-2 rounded-lg bg-bg px-3 py-2 text-[13px] text-text-secondary">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Yanıtlanıyor…
              </div>
            )}
            <AIDisclaimer short />
          </div>
        )}

        {/* Öneriler — briefing items the AI quantified with a savings/impact figure */}
        {recommendations.length > 0 && (
          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text-secondary">
              <Sparkles className="h-3.5 w-3.5 text-brand" /> Öneriler
            </h4>
            <div className="space-y-3">
              {recommendations.map((item, i) => (
                <InsightItem key={i} item={item} />
              ))}
            </div>
          </div>
        )}

        {/* Bugünün Öncelikli İşleri */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text-secondary">
              <ListChecks className="h-3.5 w-3.5 text-brand" /> Bugünün Öncelikli İşleri
            </h4>
            <div className="flex items-center gap-1.5">
              {generatedAt && <span className="text-[10px] italic text-text-disabled">{formatDateTime(generatedAt)}</span>}
              <button onClick={onRefresh} disabled={briefingState === "loading"} title="Yenile" className="text-text-secondary hover:text-primary disabled:opacity-50" aria-label="Yenile">
                <RefreshCw className={cn("h-3.5 w-3.5", briefingState === "loading" && "animate-spin")} />
              </button>
            </div>
          </div>
          {briefingState === "loading" ? (
            <div className="flex items-center gap-2 rounded-md bg-navy-50 px-3 py-2 text-sm text-brand">
              <span className="h-2 w-2 animate-pulse rounded-full bg-brand" /> Yapay zeka projelerinizi analiz ediyor…
            </div>
          ) : briefingState === "error" ? (
            <div className="flex items-center gap-2 rounded-md bg-bg px-3 py-2 text-sm text-text-secondary">
              <Info className="h-4 w-4" /> Yapay zeka şu an kullanılamıyor.
            </div>
          ) : actions.length === 0 ? (
            <div className="flex items-center gap-2 rounded-md bg-green-50 px-3 py-2 text-sm text-success">
              <CheckCircle2 className="h-4 w-4" /> Bugün için öncelikli işlem bulunmuyor.
            </div>
          ) : (
            <div className="space-y-3">
              {actions.slice(0, 8).map((item, i) => (
                <InsightItem key={i} item={item} />
              ))}
            </div>
          )}
          {briefingState === "ready" && <AIDisclaimer />}
        </div>

        <button onClick={onGoToTasks} className="flex w-full items-center justify-center gap-1 rounded-lg border border-border py-2 text-sm font-medium text-brand hover:bg-navy-50">
          Görevlerime git →
        </button>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
        className="border-t border-border p-3"
      >
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2 focus-within:border-brand">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Soru sor…" className="flex-1 bg-transparent py-2 text-sm outline-none" />
          <button type="submit" disabled={!input.trim() || asking} className="text-brand disabled:text-text-disabled" aria-label="Gönder">
            <Send className="h-4 w-4" />
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * Responsive wrapper for the Yapı AI rail:
 *  - xl+: a fixed ~360px right column, collapsible to a slim reopen tab.
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
        <aside className="sticky top-6 hidden h-[calc(100vh-7rem)] w-[360px] shrink-0 flex-col self-start overflow-hidden rounded-xl border border-border bg-surface shadow-sm xl:flex">
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
