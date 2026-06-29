import * as React from "react";
import { ChevronDown, ChevronRight, MoreHorizontal, Pencil, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { RowMenu, MenuItem } from "@/components/ui";
import { formatDateTime, formatRelativeTime, recencyBucket } from "@/utils/format";
import { AGENT_PRESETS, type AgentPreset } from "./agentPresets";

// CR-038 §B3 — the Yapı AI left rail (Cowork/Dema style): new chat · search ·
// premade agents · uygulamalar (yakında) · grouped recent sessions with inline
// rename + delete. Pure presentation over the page's conversation state.
interface RailConversation {
  id: string;
  title: string;
  updatedAt: string;
}

interface Props {
  conversations: RailConversation[];
  activeId: string | null;
  activeAgentId: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onNewChat: () => void;
  onPickAgent: (preset: AgentPreset) => void;
}

const BUCKET_LABELS: Record<"today" | "week" | "older", string> = {
  today: "Bugün",
  week: "Son 7 gün",
  older: "Daha eski",
};

export function AgentConversationsRail({
  conversations,
  activeId,
  activeAgentId,
  onSelect,
  onDelete,
  onRename,
  onNewChat,
  onPickAgent,
}: Props) {
  const [search, setSearch] = React.useState("");
  const [agentsOpen, setAgentsOpen] = React.useState(true);
  const [renamingId, setRenamingId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");

  const norm = (s: string) => s.toLocaleLowerCase("tr");
  const q = norm(search.trim());
  const filtered = q ? conversations.filter((c) => norm(c.title).includes(q)) : conversations;

  // Group newest-first into recency buckets.
  const groups: { key: "today" | "week" | "older"; items: RailConversation[] }[] = (
    ["today", "week", "older"] as const
  )
    .map((key) => ({ key, items: filtered.filter((c) => recencyBucket(c.updatedAt) === key) }))
    .filter((g) => g.items.length > 0);

  const startRename = (c: RailConversation) => {
    setRenamingId(c.id);
    setDraft(c.title);
  };
  const commitRename = () => {
    if (renamingId) {
      const t = draft.trim();
      if (t) onRename(renamingId, t);
    }
    setRenamingId(null);
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <button
        onClick={onNewChat}
        className="focus-ring flex h-10 w-full items-center justify-center gap-1.5 rounded-control bg-primary text-sm font-medium text-white transition hover:bg-primary-light"
      >
        <Plus className="h-4 w-4" /> Yeni sohbet
      </button>

      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Ara…"
          aria-label="Sohbetlerde ara"
          className="focus-ring h-9 w-full rounded-control border border-border bg-surface pl-8 pr-3 text-[13px] outline-none focus:border-brand"
        />
      </div>

      {/* Ajanlar (premade agents) */}
      <div>
        <button
          onClick={() => setAgentsOpen((o) => !o)}
          aria-expanded={agentsOpen}
          className="focus-ring flex w-full items-center gap-1 rounded-control px-1 py-1 text-[10px] font-semibold uppercase tracking-wide text-text-faint hover:text-text-secondary"
        >
          {agentsOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          Ajanlar
        </button>
        {agentsOpen && (
          <div className="mt-1 space-y-0.5">
            {AGENT_PRESETS.map((a) => {
              const active = a.id === activeAgentId;
              return (
                <button
                  key={a.id}
                  onClick={() => onPickAgent(a)}
                  title={a.description}
                  className={cn(
                    "focus-ring flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left transition-colors",
                    active ? "bg-blue-soft text-brand" : "text-text-secondary hover:bg-surface-hover"
                  )}
                >
                  <a.icon className={cn("h-4 w-4 shrink-0", active ? "text-brand" : "text-text-muted")} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-text-primary">{a.label}</span>
                    <span className="block truncate text-[11px] text-text-faint">{a.description}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Uygulamalar (slot for the future skills/apps view) */}
      <div className="flex items-center justify-between rounded-control px-1 py-1">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-text-faint">Uygulamalar</span>
        <span className="rounded-sm bg-surface-hover px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-text-faint">
          Yakında
        </span>
      </div>

      {/* Son sohbetler */}
      <div className="min-h-0 flex-1">
        <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wide text-text-faint">Son sohbetler</div>
        <div className="space-y-2">
          {filtered.length === 0 && (
            <p className="px-1 py-2 text-xs text-text-secondary">
              {q ? "Sonuç bulunamadı." : "Henüz sohbet yok — yukarıdan başlayın."}
            </p>
          )}
          {groups.map((g) => (
            <div key={g.key}>
              <div className="px-1 pb-0.5 text-[10px] font-medium text-text-faint">{BUCKET_LABELS[g.key]}</div>
              <div className="space-y-0.5">
                {g.items.map((c) => {
                  const active = c.id === activeId;
                  if (renamingId === c.id) {
                    return (
                      <input
                        key={c.id}
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onBlur={commitRename}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            commitRename();
                          } else if (e.key === "Escape") {
                            e.preventDefault();
                            setRenamingId(null);
                          }
                        }}
                        aria-label="Sohbeti yeniden adlandır"
                        className="focus-ring w-full rounded-control border border-brand bg-surface px-2 py-1.5 text-[13px] outline-none"
                      />
                    );
                  }
                  return (
                    <div
                      key={c.id}
                      className={cn(
                        "group flex items-center gap-1 rounded-control px-2 py-1.5 transition-colors",
                        active ? "bg-blue-soft" : "hover:bg-surface-hover"
                      )}
                    >
                      <button onClick={() => onSelect(c.id)} className="min-w-0 flex-1 text-left">
                        <div
                          className={cn("truncate text-[13px] font-medium", active ? "text-brand" : "text-text-primary")}
                          title={c.title}
                        >
                          {c.title}
                        </div>
                        <div className="text-[10px] text-text-faint" title={formatDateTime(c.updatedAt)}>
                          {formatRelativeTime(c.updatedAt)}
                        </div>
                      </button>
                      <RowMenu
                        triggerLabel="Sohbet işlemleri"
                        trigger={
                          <span className="flex h-6 w-6 items-center justify-center rounded-control text-text-muted opacity-0 transition hover:bg-surface-hover hover:text-text-primary group-hover:opacity-100">
                            <MoreHorizontal className="h-4 w-4" />
                          </span>
                        }
                      >
                        {(close) => (
                          <>
                            <MenuItem icon={Pencil} onClick={() => { close(); startRename(c); }}>Yeniden adlandır</MenuItem>
                            <MenuItem icon={Trash2} danger onClick={() => { close(); onDelete(c.id); }}>Sil</MenuItem>
                          </>
                        )}
                      </RowMenu>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-1.5 px-1 pt-1 text-[10px] text-text-faint">
        <Sparkles className="h-3 w-3 text-brand" /> Yapı AI · önerir, siz onaylarsınız
      </div>
    </div>
  );
}
