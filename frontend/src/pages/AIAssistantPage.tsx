import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { AgentSteps, type AgentStep } from "@/components/ai/AgentSteps";
import { AgentMessage } from "@/components/ai/AgentMessage";
import { AgentConversationsRail } from "@/components/ai/AgentConversationsRail";
import { SessionOutputsPanel, type SkillRunOutput } from "@/components/ai/SessionOutputsPanel";
import { AGENT_PRESETS, DEFAULT_AGENT, agentById, agentByScope, type AgentPreset } from "@/components/ai/agentPresets";
import { MarkdownText } from "@/components/MarkdownText";
import { useLeftRail, useRightPanel } from "@/components/layout/ShellSlots";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiGet, apiPut } from "@/lib/api";
import { apiPost } from "@/lib/api";
import { streamAgent } from "@/lib/agentStream";
import { toast } from "@/store/toast";
import type { Project } from "@/types";
import type { AgentChartSpec, AgentResponse, AgentScope, Citation, ProposedAction } from "@/types/agent";
import { ArrowUp, ChevronDown, FolderKanban, Loader2, Plus, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Menu, MenuItem } from "@/components/ui";

const PRESETS = [
  // CR-007-F: headline agent scenario (edit the firm name before sending).
  "[Firma adı] ile son 6 ayda ne kadar iş yaptık?",
  "Tedarikçilerimizi bu yılki harcamaya göre karşılaştır.",
  "Hangi proje en fazla para kaybetme riski taşıyor?",
  "Bu ay marj neden düştü?",
  "Hangi tedarikçinin en yüksek vadesi geçmiş borcu var?",
  "Önümüzdeki 90 günde ne kadar nakit ihtiyacımız var?",
  "Hangi maliyet kategorisi bütçesini aştı?",
  "Önce hangi hakedişi takip etmeliyiz?",
];

interface Msg {
  role: "user" | "ai";
  text: string;
  at?: string;
  // CR-007-F: agent extras (in-session; dropped by the conversation store on persist).
  charts?: AgentChartSpec[];
  citations?: Citation[];
  tools_used?: string[];
  // CR-024: explainability + feedback (in-session only).
  row_counts?: Record<string, number>;
  query_log_id?: string | null;
  // Cowork-style thinking steps recorded during the turn (in-session only).
  steps?: AgentStep[];
  // CR-011 rich steps (in-session only).
  tool_summaries?: Record<string, Record<string, unknown>>;
  usage?: { input_tokens: number; output_tokens: number };
  // CR-011-C (in-session): proposed-action cards (authoring / write proposals).
  proposed_actions?: ProposedAction[];
  // CR-038 §G (reserved — declared, NOT set): kept open for CR-039 persistence.
  attachments?: import("@/types/agent").AgentAttachment[];
  artifacts?: import("@/types/agent").AgentArtifact[];
}

// CR-011-D §4.1: the step label shown before the first server `step` event arrives.
const INITIAL_STEP = "Soru anlaşılıyor…";

interface Conversation {
  id: string;
  title: string;
  messages: Msg[];
  projectId: string;
  updatedAt: string;
  // CR-038 §G (additive, client-side like projectId): which premade-agent lens
  // (scope) the session was started with. Server has no scope field — best-effort.
  scope?: AgentScope | null;
  // CR-038: the saved report this session is grounded in (CR-035 hand-off). Fixed
  // at creation so the grounding can't leak onto other sessions. Client-side only.
  reportId?: string | null;
}

const STORAGE_KEY = "yapi_ai_conversations";
const ACTIVE_KEY = "yapi_ai_active";

// A stable empty list so derived memos don't churn when there is no active chat.
const EMPTY_MSGS: Msg[] = [];

// CR-039 — the active authoring draft = the draft_* proposed-action on the most
// recent AI message, unless the user already resolved it (created/edited/cancelled).
// DERIVED, not stored (no second source of truth → no CR-038 render-loop risk).
// CR-044 — also threads draft_skill so refining a skill edits the real plan.
type ActiveDraft = {
  kind: string;
  title?: string;
  spec?: unknown;
  widgets?: unknown[];
  // CR-044 — a skill draft carries its compiled plan + format + instruction so the
  // agent refines the REAL plan instead of recompiling from scratch.
  plan?: unknown;
  format?: string;
  instruction?: string;
} | null;

// Keyed by content so a resolved draft stops being threaded. Tradeoff: a later
// BYTE-IDENTICAL re-proposal after İptal is also skipped for one turn (rare; the
// card + Oluştur still work, only the refine-context optimization is missed).
// CR-044 — a skill keys on its plan (+ format) since it has no top-level spec/widgets.
function draftKey(a: { kind: string; title?: string; spec?: unknown; widgets?: unknown[]; plan?: unknown; format?: string }): string {
  const shape = a.spec ?? a.widgets ?? a.plan ?? null;
  return `${a.kind}:${a.title ?? ""}:${a.format ?? ""}:${JSON.stringify(shape)}`;
}

const DRAFT_KINDS = new Set(["draft_report", "draft_dashboard", "draft_skill"]);

function deriveActiveDraft(messages: Msg[], dismissed: Set<string>): ActiveDraft {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role !== "ai") continue;
    const da = (messages[i].proposed_actions ?? []).find((a) => DRAFT_KINDS.has(a.kind));
    if (!da) return null; // the latest AI turn carried no draft → nothing active
    if (dismissed.has(draftKey(da))) return null; // already created/edited/cancelled
    return {
      kind: da.kind,
      title: da.title,
      spec: da.spec,
      widgets: da.widgets,
      plan: da.plan,
      format: da.format,
      instruction: da.instruction,
    };
  }
  return null;
}

const newId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `c_${Date.now()}_${Math.random().toString(36).slice(2)}`;

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

interface ServerConversation {
  id: string;
  title: string;
  messages: Msg[];
  project_id: string | null;
  updated_at: string | null;
  scope?: AgentScope | null;
}
const toConversation = (c: ServerConversation): Conversation => ({
  id: c.id,
  title: c.title,
  messages: Array.isArray(c.messages) ? c.messages : [],
  projectId: c.project_id ?? "",
  updatedAt: c.updated_at ?? new Date().toISOString(),
  scope: c.scope ?? null,
});

export default function AIAssistantPage() {
  const { data: projects } = useFetch<Project[]>("/projects");
  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeId, setActiveId] = useState<string | null>(() => {
    const saved = localStorage.getItem(ACTIVE_KEY);
    return saved && loadConversations().some((c) => c.id === saved) ? saved : null;
  });
  const [projectId, setProjectId] = useState(() => {
    const saved = localStorage.getItem(ACTIVE_KEY);
    return loadConversations().find((c) => c.id === saved)?.projectId ?? "";
  });
  // CR-038 §B5: which premade-agent lens is active (drives the `scope`).
  const [activeAgentId, setActiveAgentId] = useState<string>(() => {
    const saved = localStorage.getItem(ACTIVE_KEY);
    const c = loadConversations().find((x) => x.id === saved);
    return agentByScope(c?.scope ?? null).id;
  });
  const activeAgent = agentById(activeAgentId);

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [thinkingStep, setThinkingStep] = useState<string | null>(null);
  const [liveSteps, setLiveSteps] = useState<AgentStep[]>([]);
  const stepsRef = useRef<AgentStep[]>([]);
  const [liveText, setLiveText] = useState("");
  const [showAllPresets, setShowAllPresets] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  // CR-039 — keys of drafts the user has resolved (created/edited/cancelled), so
  // deriveActiveDraft stops threading them. Read only inside ask() (an event
  // handler), never in a render/effect → cannot loop.
  const dismissedRef = useRef<Set<string>>(new Set());
  const location = useLocation();
  const navigate = useNavigate();

  // CR-035 — Rapor Stüdyosu hand-off (read ONCE from location.state on mount).
  // CR-038: the grounding belongs to the ORIGINATING conversation (stored on it,
  // like `scope`), and the page-level handoff is cleared when the user moves to a
  // different session — so a saved-report Q&A never leaks onto unrelated chats.
  const handoff = (location.state as { report_id?: string | null; studioIntent?: "report" | "dashboard" } | null) ?? null;
  const [studioReportId, setStudioReportId] = useState<string | null>(handoff?.report_id ?? null);
  const [studioIntent, setStudioIntent] = useState<"report" | "dashboard" | null>(handoff?.studioIntent ?? null);

  const activeConv = conversations.find((c) => c.id === activeId) ?? null;
  const messages = activeConv?.messages ?? EMPTY_MSGS;

  const projectList = useMemo(() => (projects ?? []).map((p) => ({ id: p.id, name: p.name })), [projects]);

  // CR-007-I: most recent chart across the conversation (shown on the Tuval).
  const latestChartInfo = useMemo<{ spec: AgentChartSpec; msgIndex: number } | null>(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const cs = messages[i].charts;
      if (cs && cs.length) return { spec: cs[cs.length - 1], msgIndex: i };
    }
    return null;
  }, [messages]);
  const latestChart = latestChartInfo?.spec ?? null;

  // CR-044 — this session's generated files: every `run_result` proposed-action
  // across the conversation, newest first. Session-scoped (the durable record is
  // the backend skill_runs table); drives the SessionOutputsPanel "Üretilen
  // dosyalar" list + de-duped by run_id.
  const skillRuns = useMemo<SkillRunOutput[]>(() => {
    const out: SkillRunOutput[] = [];
    const seen = new Set<string>();
    for (let i = messages.length - 1; i >= 0; i--) {
      for (const a of messages[i].proposed_actions ?? []) {
        if (a.kind !== "run_result" || !a.run_id || seen.has(a.run_id)) continue;
        seen.add(a.run_id);
        out.push({
          run_id: a.run_id,
          file_name: a.file_name ?? "rapor",
          format: (a.format as "xlsx" | "pdf") ?? "xlsx",
          download_url: a.download_url ?? "",
        });
      }
    }
    return out;
  }, [messages]);

  const [pinnedKeys, setPinnedKeys] = useState<Set<string>>(new Set());

  const pinChart = useCallback(async () => {
    if (!latestChartInfo) return;
    const key = `chart:${activeId ?? "new"}:${latestChartInfo.msgIndex}`;
    if (pinnedKeys.has(key)) {
      toast.info("Bu grafik zaten çalışma alanınızda");
      return;
    }
    try {
      await apiPost("/workspace/items", {
        title: latestChartInfo.spec.title || "Grafik",
        item_type: "chart",
        payload: latestChartInfo.spec,
        source_conversation_id: activeId || null,
      });
      setPinnedKeys((prev) => new Set(prev).add(key));
      toast.success("Çalışma alanınıza eklendi");
    } catch {
      toast.error("Çalışma alanına eklenemedi");
    }
  }, [latestChartInfo, activeId, pinnedKeys]);

  const pinAnalysis = async (m: Msg, i: number) => {
    const key = `analysis:${activeId ?? "new"}:${i}`;
    if (pinnedKeys.has(key)) {
      toast.info("Bu analiz zaten çalışma alanınızda");
      return;
    }
    try {
      await apiPost("/workspace/items", {
        title: (m.text.split("\n")[0] || "Analiz").replace(/[*#]/g, "").slice(0, 80) || "Analiz",
        item_type: "analysis",
        payload: { answer_markdown: m.text, citations: m.citations ?? [] },
        source_conversation_id: activeId || null,
      });
      setPinnedKeys((prev) => new Set(prev).add(key));
      toast.success("Çalışma alanınıza eklendi");
    } catch {
      toast.error("Çalışma alanına eklenemedi");
    }
  };

  // Cache to localStorage for instant paint on the next visit/refresh.
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
  }, [conversations]);
  useEffect(() => {
    if (activeId) localStorage.setItem(ACTIVE_KEY, activeId);
    else localStorage.removeItem(ACTIVE_KEY);
  }, [activeId]);

  // CR-004-I: auto-scroll to the newest message / streamed token.
  useEffect(() => {
    if (messages.length === 0) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeId, messages.length, loading, liveText]);

  // CR-011-D: abort any in-flight token stream when the page unmounts.
  useEffect(() => () => abortRef.current?.(), []);

  // Push a conversation to the server (fire-and-forget). Scope is client-side
  // only — the PUT body stays exactly as before (no backend change).
  const syncConversation = (id: string, title: string, msgs: Msg[], projId: string) => {
    apiPut(`/ai/conversations/${id}`, { title, messages: msgs, project_id: projId || null }).catch(() => {});
  };

  // Leaving the Studio hand-off session drops its grounding so the next NEW chat
  // isn't force-grounded in the original report (existing chats carry their own).
  const clearHandoff = useCallback(() => {
    setStudioReportId(null);
    setStudioIntent(null);
  }, []);

  // CR-039 — a draft was created/edited/cancelled in the card: mark it resolved so
  // the next ask() no longer threads it as the active refine draft.
  const handleDraftResolved = useCallback((action: ProposedAction) => {
    dismissedRef.current.add(draftKey(action));
  }, []);

  const startNewChat = useCallback(() => {
    setActiveId(null);
    setInput("");
    setActiveAgentId(DEFAULT_AGENT.id);
    clearHandoff();
    dismissedRef.current = new Set(); // fresh session → forget resolved drafts
  }, [clearHandoff]);

  const pickAgent = useCallback(
    (preset: AgentPreset) => {
      setActiveAgentId(preset.id);
      setActiveId(null);
      setInput("");
      clearHandoff();
      dismissedRef.current = new Set();
    },
    [clearHandoff]
  );

  const selectConversation = useCallback(
    (id: string) => {
      const c = conversations.find((x) => x.id === id);
      setActiveId(id);
      setProjectId(c?.projectId ?? "");
      setActiveAgentId(agentByScope(c?.scope ?? null).id);
      setInput("");
      clearHandoff();
    },
    [conversations, clearHandoff]
  );

  const deleteConversation = useCallback((id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    setActiveId((cur) => (cur === id ? null : cur));
    apiDelete(`/ai/conversations/${id}`).catch(() => {});
  }, []);

  const renameConversation = useCallback(
    (id: string, title: string) => {
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
      const c = conversations.find((x) => x.id === id);
      if (c) apiPut(`/ai/conversations/${id}`, { title, messages: c.messages, project_id: c.projectId || null }).catch(() => {});
    },
    [conversations]
  );

  // {role:"ai", text} -> {role:"assistant", content}; user unchanged (§0 S2).
  const toAgentMessages = (msgs: Msg[]) => msgs.map((m) => ({ role: m.role === "ai" ? "assistant" : "user", content: m.text }));

  const ask = (question: string) => {
    if (!question.trim() || loading) return;
    const userMsg: Msg = { role: "user", text: question };
    const now = new Date().toISOString();

    const existing = activeId ? conversations.find((c) => c.id === activeId) : null;
    const id = existing ? existing.id : newId();
    const title = existing ? existing.title : question.length > 60 ? `${question.slice(0, 60)}…` : question;
    const afterUser = [...(existing?.messages ?? []), userMsg];
    // Scope + report grounding are fixed at conversation creation; follow-ups keep
    // them. A new (non-handoff) chat carries no report_id even if this page was
    // first opened from a Studio hand-off (the handoff is cleared on session switch).
    const scope: AgentScope | null = existing ? existing.scope ?? null : activeAgent.scope ?? null;
    const reportId: string | null = existing ? existing.reportId ?? null : studioReportId || null;
    // CR-039 — if the latest AI turn left an unresolved draft, thread it so the
    // agent edits the REAL spec on this (refine) turn instead of rebuilding it.
    const activeDraft = deriveActiveDraft(existing?.messages ?? EMPTY_MSGS, dismissedRef.current);

    if (existing) {
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages: afterUser, updatedAt: now } : c)));
    } else {
      setConversations((prev) => [{ id, title, messages: afterUser, projectId, updatedAt: now, scope, reportId }, ...prev]);
      setActiveId(id);
    }
    syncConversation(id, title, afterUser, projectId);
    setInput("");
    setLoading(true);
    setLiveText("");
    setThinkingStep(INITIAL_STEP);
    stepsRef.current = [];
    setLiveSteps([]);

    abortRef.current?.();

    const finish = (aiMsg: Msg) => {
      const afterAi = [...afterUser, aiMsg];
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages: afterAi, updatedAt: new Date().toISOString() } : c)));
      syncConversation(id, title, afterAi, projectId);
      abortRef.current = null;
      setLoading(false);
      setThinkingStep(null);
      setLiveText("");
      stepsRef.current = [];
      setLiveSteps([]);
    };

    abortRef.current = streamAgent(
      // CR-038/CR-039: scope + draft threaded additively. report_id + project_id
      // stay on EVERY body. draft is the active refine context (null when none).
      { messages: toAgentMessages(afterUser), project_id: projectId || null, report_id: reportId, scope,
        draft: activeDraft },
      {
        onDelta: (text) => setLiveText((prev) => prev + text),
        onStep: (label, tool, detail) => {
          setLiveText("");
          if (label) setThinkingStep(label);
          if (label || tool) {
            const next = [
              ...stepsRef.current,
              {
                label: label ?? "",
                tool: tool ?? "",
                input: (detail?.input as Record<string, unknown> | undefined) ?? undefined,
                note: detail?.note ?? undefined,
                thinking: detail?.thinking ?? undefined,
              },
            ];
            stepsRef.current = next;
            setLiveSteps(next);
          }
        },
        onFinal: (res) =>
          finish({
            role: "ai",
            text: res.answer_markdown || "Bu konuda veri bulunamadı.",
            at: res.generated_at,
            charts: res.charts ?? [],
            citations: res.citations ?? [],
            tools_used: res.tools_used ?? [],
            row_counts: res.row_counts ?? {},
            query_log_id: res.query_log_id ?? null,
            proposed_actions: res.proposed_actions ?? [],
            tool_summaries: res.tool_summaries ?? {},
            usage: res.usage,
            steps:
              stepsRef.current.length > 0
                ? stepsRef.current
                : (res.tools_used ?? []).map((t) => ({ label: "", tool: t })),
          }),
        onError: () => finish({ role: "ai", text: "AI şu an kullanılamıyor." }),
      }
    );
  };

  // Load the server copy on mount, then run any handed-off question once.
  useEffect(() => {
    let cancelled = false;
    const handed = (location.state as { q?: string } | null)?.q;
    apiGet<ServerConversation[]>("/ai/conversations")
      .then(({ data }) => {
        if (cancelled) return;
        const mapped = (data ?? []).map(toConversation);
        setConversations(mapped);
        setActiveId((cur) => (cur && mapped.some((c) => c.id === cur) ? cur : null));
      })
      .catch(() => {
        /* offline / error: keep the localStorage-cached list already in state */
      })
      .finally(() => {
        if (cancelled || !handed) return;
        ask(handed);
        window.history.replaceState({}, "");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Build a completed AI message as an AgentResponse so it renders through the
  // SAME shared renderer (AgentMessage → AgentAnswerBody) as the drawer/rail.
  const resFromMsg = (m: Msg): AgentResponse => ({
    answer_markdown: m.text,
    charts: m.charts ?? [],
    citations: m.citations ?? [],
    tools_used: m.tools_used ?? [],
    generated_at: m.at ?? "",
    row_counts: m.row_counts ?? {},
    query_log_id: m.query_log_id ?? null,
    proposed_actions: m.proposed_actions ?? [],
    tool_summaries: m.tool_summaries ?? {},
    usage: m.usage,
  });

  // --- contextual rail + right panel (registered into the durable shell slots) //
  const railNode = useMemo(
    () => (
      <AgentConversationsRail
        conversations={conversations}
        activeId={activeId}
        activeAgentId={activeAgentId}
        onSelect={selectConversation}
        onDelete={deleteConversation}
        onRename={renameConversation}
        onNewChat={startNewChat}
        onPickAgent={pickAgent}
      />
    ),
    [conversations, activeId, activeAgentId, selectConversation, deleteConversation, renameConversation, startNewChat, pickAgent]
  );
  useLeftRail(railNode);

  const goWorkspace = useCallback(() => navigate("/workspace"), [navigate]);
  const rightPanelNode = useMemo(
    () => (
      <SessionOutputsPanel
        latestChart={latestChart}
        canPin={!!latestChart}
        onPin={pinChart}
        onViewWorkspace={goWorkspace}
        projectId={projectId}
        onProjectChange={setProjectId}
        projects={projectList}
        skillRuns={skillRuns}
      />
    ),
    [latestChart, pinChart, goWorkspace, projectId, projectList, skillRuns]
  );
  useRightPanel(rightPanelNode);

  const placeholder = studioIntent
    ? "Ne görmek istediğinizi yazın — örn. 'daire tipine göre kâr/zarar raporu yap'"
    : messages.length === 0
    ? "Başlamak için bir şey sorun…"
    : "Sorunuzu yazın…";

  const composer = (
    <Composer
      value={input}
      onChange={setInput}
      onSubmit={() => ask(input)}
      placeholder={placeholder}
      loading={loading}
      projectId={projectId}
      projects={projectList}
      onProjectChange={setProjectId}
    />
  );

  const visiblePresets = showAllPresets ? PRESETS : PRESETS.slice(0, 6);

  return (
    <div className="flex h-full flex-col">
      <div className="mx-auto flex w-full max-w-[760px] flex-1 flex-col px-4 sm:px-6">
        {messages.length === 0 ? (
          // --- Opening scene (the hero IS the header) ----------------------- //
          <div className="flex flex-1 flex-col justify-center py-8">
            <div className="mb-6 text-center">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-brand to-teal text-2xl font-bold text-white shadow-sm">
                Y
              </div>
              <h1 className="text-2xl font-bold text-text-primary">Bugün birlikte ne yapalım?</h1>
              <p className="mt-1.5 text-sm text-text-secondary">
                {activeAgent.scope ? `${activeAgent.label} · ${activeAgent.description}` : "Araçlarla analiz yapan yapay zeka ajanı — Türkçe sorun."}
              </p>
            </div>

            {studioIntent && (
              <div className="mb-4 flex items-start gap-2 rounded-control border border-brand/40 bg-blue-soft p-3 text-[13px] text-text-primary">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
                <span>
                  {studioIntent === "dashboard"
                    ? "Nasıl bir pano istediğinizi anlatın — Yapı AI önerip onayınıza sunar."
                    : "Nasıl bir rapor istediğinizi anlatın — Yapı AI önerip onayınıza sunar."}
                </span>
              </div>
            )}

            {composer}
            <div className="mt-2 flex justify-center">
              <AiTrustBadge compact />
            </div>

            {/* Suggestion chips */}
            <div className="mt-6">
              <div className="flex flex-wrap justify-center gap-2">
                {visiblePresets.map((q) => (
                  <button
                    key={q}
                    onClick={() => ask(q)}
                    className="focus-ring rounded-control border border-border bg-surface px-3 py-1.5 text-left text-[13px] text-text-secondary transition-colors hover:bg-blue-soft hover:text-brand"
                  >
                    {q}
                  </button>
                ))}
              </div>
              {!showAllPresets && PRESETS.length > 6 && (
                <div className="mt-2 text-center">
                  <button onClick={() => setShowAllPresets(true)} className="focus-ring rounded-sm text-xs font-medium text-brand hover:underline">
                    Daha fazla öneri
                  </button>
                </div>
              )}
            </div>

            {/* Premade agents */}
            <div className="mt-8">
              <div className="mb-2 text-center text-xs font-medium text-text-secondary">Bir ajanla başla</div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {AGENT_PRESETS.map((a) => {
                  const active = a.id === activeAgentId;
                  return (
                    <button
                      key={a.id}
                      onClick={() => pickAgent(a)}
                      title={a.description}
                      className={cnAgentCard(active)}
                    >
                      <a.icon className={`h-4 w-4 shrink-0 ${active ? "text-brand" : "text-text-muted"}`} />
                      <span className="min-w-0">
                        <span className="block truncate text-[13px] font-semibold text-text-primary">{a.label}</span>
                        <span className="block truncate text-[11px] text-text-faint">{a.description}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        ) : (
          // --- Active thread ------------------------------------------------ //
          <>
            <div className="flex-1 space-y-6 overflow-y-auto py-6">
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <div key={i} className="flex justify-end">
                    <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-surface px-4 py-2.5 text-sm text-text-primary shadow-sm">
                      {m.text}
                    </div>
                  </div>
                ) : (
                  <div key={i} className="flex gap-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-2 text-white">
                      <Sparkles className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1 pt-0.5 text-sm leading-relaxed text-text-primary">
                      <AgentMessage
                        res={resFromMsg(m)}
                        question={messages[i - 1]?.text ?? ""}
                        onNavigate={(to) => navigate(to)}
                        steps={m.steps ?? []}
                        rowCounts={m.row_counts}
                        toolSummaries={m.tool_summaries}
                        usage={m.usage}
                        onPin={m.at ? () => pinAnalysis(m, i) : undefined}
                        showDisclaimer
                        showGeneratedAtLine={!!m.at}
                        onResolve={handleDraftResolved}
                      />
                    </div>
                  </div>
                )
              )}

              {loading && (
                <div className="flex gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-2 text-white">
                    <Sparkles className="h-4 w-4 animate-pulse" />
                  </span>
                  <div className="min-w-0 flex-1 pt-0.5">
                    {liveSteps.length > 0 && <AgentSteps steps={liveSteps} running />}
                    {liveText ? (
                      <>
                        <div className="text-sm leading-relaxed text-text-primary">
                          <MarkdownText text={liveText} />
                        </div>
                        <div className="mt-2 flex items-center gap-2 text-xs text-text-secondary">
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-brand" /> {thinkingStep ?? "Yanıt yazılıyor…"}
                        </div>
                      </>
                    ) : (
                      liveSteps.length === 0 && (
                        <div className="flex items-center gap-2 pt-1 text-sm text-text-secondary">
                          <Loader2 className="h-4 w-4 animate-spin text-brand" /> {thinkingStep ?? "Yanıt hazırlanıyor…"}
                        </div>
                      )
                    )}
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>

            <div className="sticky bottom-0 shrink-0 bg-bg pb-4 pt-2">{composer}</div>
          </>
        )}
      </div>
    </div>
  );
}

function cnAgentCard(active: boolean): string {
  return [
    "focus-ring flex items-start gap-2 rounded-card border bg-surface p-2.5 text-left transition-colors",
    active ? "border-brand bg-blue-soft" : "border-border hover:border-brand hover:bg-blue-soft/50",
  ].join(" ");
}

// CR-038 §B4 — premium composer: auto-grow textarea (Enter sends / Shift+Enter
// newline), a reserved (disabled) attach affordance, a project-context chip, and
// a circular send button.
function Composer({
  value,
  onChange,
  onSubmit,
  placeholder,
  loading,
  projectId,
  projects,
  onProjectChange,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder: string;
  loading: boolean;
  projectId: string;
  projects: { id: string; name: string }[];
  onProjectChange: (id: string) => void;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [value]);
  const projectName = projectId ? projects.find((p) => p.id === projectId)?.name ?? "Proje" : "Tüm projeler";

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="w-full"
    >
      <div className="rounded-2xl border border-border bg-surface shadow-sm transition focus-within:border-brand">
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={1}
          placeholder={placeholder}
          aria-label="Soru"
          className="block max-h-[200px] w-full resize-none bg-transparent px-4 pt-3 text-sm leading-relaxed outline-none placeholder:text-text-faint"
        />
        <div className="flex items-center gap-1.5 px-2.5 pb-2.5 pt-1">
          {/* CR-038 §7-E: attach is RESERVED — present but disabled. */}
          <button
            type="button"
            disabled
            title="Dosya ekleme yakında"
            aria-label="Dosya ekle (yakında)"
            className="flex h-8 w-8 cursor-not-allowed items-center justify-center rounded-full text-text-muted opacity-50"
          >
            <Plus className="h-4 w-4" />
          </button>
          <Menu
            align="left"
            triggerLabel="Proje seç"
            width={240}
            triggerClassName="flex h-8 max-w-[180px] items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 text-[12px] font-medium text-text-secondary transition-colors hover:bg-surface-hover"
            trigger={
              <>
                <FolderKanban className="h-3.5 w-3.5 shrink-0 text-text-muted" />
                <span className="truncate">{projectName}</span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-text-muted" />
              </>
            }
          >
            {(close) => (
              <>
                <MenuItem onClick={() => { onProjectChange(""); close(); }}>
                  <span className={!projectId ? "font-semibold text-brand" : ""}>Tüm Projeler</span>
                </MenuItem>
                {projects.map((p) => (
                  <MenuItem key={p.id} onClick={() => { onProjectChange(p.id); close(); }}>
                    <span className={projectId === p.id ? "font-semibold text-brand" : ""}>{p.name}</span>
                  </MenuItem>
                ))}
              </>
            )}
          </Menu>
          <div className="flex-1" />
          <button
            type="submit"
            disabled={loading || !value.trim()}
            aria-label="Gönder"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-white transition hover:bg-primary-light disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </form>
  );
}
