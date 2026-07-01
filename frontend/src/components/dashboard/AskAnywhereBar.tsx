import { ArrowRight, CornerDownLeft, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface SuggestedAction {
  label: string;
  onClick: () => void;
}

// CR-028 §3.2.1 + §3.2.3: a prominent ask-anywhere bar + read-only suggested
// chips. Submitting calls the cited agent (handled by the parent via onAsk →
// AskAgentDrawer). Prefill chips fill the bar with a question; action chips are
// strictly navigational/read-only (no create/flag/post — those are CR-011).
export function AskAnywhereBar({
  onAsk,
  prefills = [],
  actions = [],
}: {
  onAsk: (q: string) => void;
  prefills?: string[];
  actions?: SuggestedAction[];
}) {
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // ⌘K focuses this bar. Capture phase + stopImmediatePropagation beats the
  // global AppLayout ⌘K→CommandPalette binding WHILE Ana Sayfa is mounted; on
  // every other page the global palette shortcut is untouched.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        e.stopImmediatePropagation();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, []);

  const submit = () => {
    const t = q.trim();
    if (t) onAsk(t);
  };

  const prefill = (text: string) => {
    setQ(text);
    inputRef.current?.focus();
  };

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 rounded-card border border-border bg-surface px-3 py-2 shadow-card transition focus-within:border-brand">
        <Sparkles className="h-4 w-4 shrink-0 text-brand" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="Yapı'ya sor: portföyünüz hakkında bir şey sorun…"
          aria-label="Yapı'ya sor"
          className="h-7 w-full bg-transparent text-sm outline-none placeholder:text-text-disabled"
        />
        <kbd className="hidden shrink-0 rounded border border-border bg-bg px-1.5 py-0.5 text-[10px] text-text-disabled sm:inline">⌘K</kbd>
        <button
          onClick={submit}
          disabled={!q.trim()}
          aria-label="Sor"
          className="focus-ring flex h-7 w-7 shrink-0 items-center justify-center rounded-control bg-primary text-white transition hover:bg-primary-light disabled:opacity-40"
        >
          <CornerDownLeft className="h-3.5 w-3.5" />
        </button>
      </div>

      {(prefills.length > 0 || actions.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {prefills.map((p) => (
            <button
              key={p}
              onClick={() => prefill(p)}
              className="focus-ring inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-text-secondary transition hover:border-brand hover:text-brand"
            >
              <Sparkles className="h-3 w-3 text-brand" /> {p}
            </button>
          ))}
          {actions.map((a) => (
            <button
              key={a.label}
              onClick={a.onClick}
              className="focus-ring inline-flex items-center gap-1 rounded-full border border-brand/30 bg-navy-50 px-2.5 py-1 text-xs font-medium text-brand transition hover:bg-surface-hover"
            >
              {a.label} <ArrowRight className="h-3 w-3" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
