import { SideDrawer } from "@/components/SideDrawer";
import { AIDisclaimer } from "@/components/ui";
import { cn } from "@/lib/cn";
import { ChevronRight, Send, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

const SUGGESTIONS = [
  "Marjı en düşük proje hangisi ve neden?",
  "Bu ay tahsil edilecek hakedişler neler?",
];

/**
 * Inner content of the "Yapı AI" rail. Phase 1 scaffold: header, a suggested
 * question chip, and a "Soru sor…" input that hands the query to the existing
 * AI assistant. Öneriler + Bugünün Öncelikli İşleri are filled in Phase 5.
 */
function RailContent({ onClose, hideHeader }: { onClose?: () => void; hideHeader?: boolean }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");

  const ask = (text: string) => {
    const query = text.trim();
    if (!query) return;
    onClose?.();
    navigate("/ai-assistant", { state: { q: query } });
  };

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
        <p className="text-xs text-text-secondary">Projeleriniz hakkında soru sorun; öneriler ve günün öncelikli işleri burada görünecek.</p>

        <div className="space-y-1.5">
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

        {/* Öneriler / Bugünün Öncelikli İşleri — filled in Phase 5. */}
        <div className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-text-disabled">
          Öneriler ve Bugünün Öncelikli İşleri yakında burada.
        </div>

        <AIDisclaimer />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(q);
          setQ("");
        }}
        className="border-t border-border p-3"
      >
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2 focus-within:border-brand">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Soru sor…"
            className="flex-1 bg-transparent py-2 text-sm outline-none"
          />
          <button type="submit" disabled={!q.trim()} className="text-brand disabled:text-text-disabled" aria-label="Gönder">
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
export function YapiAIRail() {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <>
      {/* xl inline column */}
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
          <RailContent onClose={() => setCollapsed(true)} />
        </aside>
      )}

      {/* below-xl: floating toggle + drawer */}
      <button
        onClick={() => setDrawerOpen(true)}
        className="fixed bottom-20 right-4 z-30 flex items-center gap-2 rounded-full bg-gradient-to-br from-brand to-brand-2 px-4 py-3 text-sm font-medium text-white shadow-lg xl:hidden"
        aria-label="Yapı AI"
      >
        <Sparkles className="h-4 w-4" /> Yapı AI
      </button>
      <div className="xl:hidden">
        <SideDrawer open={drawerOpen} title="Yapı AI" onClose={() => setDrawerOpen(false)}>
          <RailContent hideHeader />
        </SideDrawer>
      </div>
    </>
  );
}
