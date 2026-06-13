import * as React from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost } from "@/lib/api";
import { useProjectStore } from "@/store/project";
import { AIDisclaimer } from "@/components/ui";
import { cn } from "@/lib/cn";
import {
  ArrowRight,
  Bell,
  Calculator,
  CornerDownLeft,
  FileBarChart,
  FileText,
  FolderKanban,
  LayoutDashboard,
  Loader2,
  MessageSquare,
  ScanLine,
  Settings,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

type NavMatch =
  | { type: "project"; label: string; id: string }
  | { type: "page"; label: string; to: string; icon: LucideIcon };

// Global command palette — navigate to pages/projects or ask the AI inline.
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { activeProjectId, activeProjectName, setActiveProject } = useProjectStore();
  const [q, setQ] = React.useState("");
  const [projects, setProjects] = React.useState<{ id: string; name: string }[]>([]);
  const [sel, setSel] = React.useState(0);
  const [asking, setAsking] = React.useState(false);
  const [answer, setAnswer] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!open) return;
    setQ("");
    setAnswer(null);
    setSel(0);
    apiGet<{ id: string; name: string; status: string }[]>("/projects")
      .then(({ data }) => setProjects((data ?? []).filter((p) => p.status === "active").map((p) => ({ id: p.id, name: p.name }))))
      .catch(() => setProjects([]));
    const t = setTimeout(() => inputRef.current?.focus(), 40);
    return () => clearTimeout(t);
  }, [open]);

  const pages: NavMatch[] = [
    { type: "page", label: "Ana Sayfa", to: "/dashboard", icon: LayoutDashboard },
    { type: "page", label: "Projeler", to: "/projects", icon: FolderKanban },
    { type: "page", label: "Hatırlatıcılar", to: "/reminders", icon: Bell },
    { type: "page", label: "Raporlar", to: "/reports", icon: FileBarChart },
    { type: "page", label: "Yapay Zeka Uyarıları", to: "/ai-alerts", icon: Sparkles },
    { type: "page", label: "AI Asistan", to: "/ai-assistant", icon: MessageSquare },
    { type: "page", label: "Belge Tara", to: "/document-capture", icon: ScanLine },
    { type: "page", label: "Ayarlar", to: "/settings", icon: Settings },
  ];
  if (activeProjectId) {
    const n = activeProjectName ?? "Proje";
    pages.push(
      { type: "page", label: `${n} · Bütçe & Maliyetler`, to: `/projects/${activeProjectId}/budget`, icon: Calculator },
      { type: "page", label: `${n} · Faturalar & Hakediş`, to: `/projects/${activeProjectId}/invoices`, icon: FileText },
      { type: "page", label: `${n} · Proje Özeti`, to: `/projects/${activeProjectId}/dashboard`, icon: LayoutDashboard }
    );
  }

  const norm = (s: string) => s.toLocaleLowerCase("tr");
  const ql = norm(q.trim());
  const navMatches: NavMatch[] = ql
    ? [
        ...projects.filter((p) => norm(p.name).includes(ql)).slice(0, 5).map((p) => ({ type: "project" as const, label: p.name, id: p.id })),
        ...pages.filter((p) => norm(p.label).includes(ql)).slice(0, 5),
      ]
    : [];
  const showAsk = ql.length > 0;
  const itemCount = navMatches.length + (showAsk ? 1 : 0);
  const showingAnswer = asking || answer != null;

  React.useEffect(() => setSel(0), [q]);

  const ask = async () => {
    const question = q.trim();
    if (!question || asking) return;
    setAsking(true);
    setAnswer(null);
    try {
      const res = await apiPost<{ answer: string }>("/ai/assistant", { question, project_id: activeProjectId || null });
      setAnswer(res.answer);
    } catch (e: any) {
      setAnswer(e.message ?? "Yapay zeka şu an kullanılamıyor.");
    } finally {
      setAsking(false);
    }
  };

  const activate = (i: number) => {
    if (i < navMatches.length) {
      const it = navMatches[i];
      if (it.type === "project") {
        setActiveProject(it.id, it.label);
        onClose();
        navigate(`/projects/${it.id}/dashboard`);
      } else {
        onClose();
        navigate(it.to);
      }
    } else if (showAsk) {
      ask();
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, itemCount - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (itemCount > 0) activate(sel);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute left-1/2 top-24 w-full max-w-xl -translate-x-1/2 px-4">
        <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl">
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Sparkles className="h-5 w-5 shrink-0 text-brand" />
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={onKey}
              placeholder="Ara, sor veya komut ver…"
              className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-text-disabled"
            />
            <kbd className="shrink-0 rounded border border-border bg-bg px-1.5 py-0.5 text-[10px] text-text-disabled">ESC</kbd>
          </div>

          <div className="max-h-[60vh] overflow-y-auto p-2">
            {showingAnswer ? (
              <div className="rounded-xl border border-border bg-bg p-3">
                <div className="mb-1 text-xs font-medium text-text-secondary">“{q.trim()}”</div>
                {asking ? (
                  <div className="flex items-center gap-2 text-sm text-text-secondary">
                    <Loader2 className="h-4 w-4 animate-spin text-brand" /> Yanıt hazırlanıyor…
                  </div>
                ) : (
                  <>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-text-primary">{answer}</p>
                    <AIDisclaimer short />
                    <button
                      onClick={() => {
                        onClose();
                        navigate("/ai-assistant", { state: { q: q.trim() } });
                      }}
                      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                    >
                      Tam sohbete git <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  </>
                )}
              </div>
            ) : (
              <>
                {navMatches.map((it, i) => {
                  const Icon = it.type === "page" ? it.icon : FolderKanban;
                  return (
                    <button
                      key={i}
                      onMouseEnter={() => setSel(i)}
                      onClick={() => activate(i)}
                      className={cn("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm", sel === i ? "bg-navy-50" : "hover:bg-bg")}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", it.type === "project" ? "text-brand" : "text-text-secondary")} />
                      <span className="flex-1 truncate text-text-primary">{it.label}</span>
                      <span className="shrink-0 text-[11px] text-text-disabled">{it.type === "project" ? "Proje" : "Sayfa"}</span>
                    </button>
                  );
                })}
                {showAsk && (
                  <button
                    onMouseEnter={() => setSel(navMatches.length)}
                    onClick={() => ask()}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm",
                      sel === navMatches.length ? "bg-navy-50" : "hover:bg-bg"
                    )}
                  >
                    <Sparkles className="h-4 w-4 shrink-0 text-brand" />
                    <span className="flex-1 truncate text-text-primary">
                      Yapay zekaya sor: <span className="font-medium">“{q.trim()}”</span>
                    </span>
                    <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-text-disabled" />
                  </button>
                )}
                {!ql && (
                  <div className="px-3 py-8 text-center text-xs text-text-secondary">
                    Sayfa veya proje aramak için yazın, ya da finansal bir soru sorun.
                    <div className="mt-1 text-text-disabled">Örn: “En düşük kar marjı hangi projede?”</div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
