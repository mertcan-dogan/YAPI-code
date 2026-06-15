import { AIDisclaimer, Select } from "@/components/ui";
import { AgentChart } from "@/components/charts/AgentChart";
import { MarkdownText } from "@/components/MarkdownText";
import { PageHeader } from "@/components/layout/AppLayout";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { toast } from "@/store/toast";
import type { Project } from "@/types";
import type { AgentChartSpec, AgentResponse, Citation } from "@/types/agent";
import { formatDateTime } from "@/utils/format";
import { ArrowUp, FileText, Loader2, Pin, Plus, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

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

// Agent response shapes live in @/types/agent (shared with AgentChart, CR-007-G/H).

interface Msg {
  role: "user" | "ai";
  text: string;
  at?: string;
  // CR-007-F: agent extras (in-session; dropped by the conversation store on persist).
  charts?: AgentChartSpec[];
  citations?: Citation[];
  tools_used?: string[];
}

// CR-007-F: tool name -> Turkish step label, for the post-response "thinking" replay.
const TOOL_STEPS: Record<string, string> = {
  list_projects: "Projeler listeleniyor…",
  get_project_financials: "Proje finansalları getiriliyor…",
  query_cost_entries: "Maliyet kayıtları inceleniyor…",
  query_client_invoices: "Hakedişler inceleniyor…",
  query_subcontractors: "Alt yükleniciler inceleniyor…",
  get_vendor_spend: "Tedarikçi harcamaları inceleniyor…",
  compare_vendors: "Tedarikçiler karşılaştırılıyor…",
  get_cashflow: "Nakit akışı hesaplanıyor…",
  get_overdue_payments: "Vadesi geçmiş ödemeler taranıyor…",
  create_chart: "Grafik oluşturuluyor…",
};

const GENERIC_STEPS = ["Soru anlaşılıyor…", "Veriler inceleniyor…", "Analiz hazırlanıyor…"];

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

interface Conversation {
  id: string;
  title: string;
  messages: Msg[];
  projectId: string;
  updatedAt: string;
}

const STORAGE_KEY = "yapi_ai_conversations";
const ACTIVE_KEY = "yapi_ai_active";

const newId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `c_${Date.now()}_${Math.random().toString(36).slice(2)}`;

// Read the localStorage cache synchronously so the first render already has the
// last-known conversations (instant paint), before the server list arrives.
function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

// Server shape → local Conversation.
interface ServerConversation {
  id: string;
  title: string;
  messages: Msg[];
  project_id: string | null;
  updated_at: string | null;
}
const toConversation = (c: ServerConversation): Conversation => ({
  id: c.id,
  title: c.title,
  messages: Array.isArray(c.messages) ? c.messages : [],
  projectId: c.project_id ?? "",
  updatedAt: c.updated_at ?? new Date().toISOString(),
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
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [thinkingStep, setThinkingStep] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();

  const activeConv = conversations.find((c) => c.id === activeId) ?? null;
  const messages = activeConv?.messages ?? [];

  // CR-007-I: the most recent chart across the conversation, shown enlarged on
  // the "Tuval" (Canvas) panel. We keep its source message index for pin dedup.
  const latestChartInfo: { spec: AgentChartSpec; msgIndex: number } | null = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const cs = messages[i].charts;
      if (cs && cs.length) return { spec: cs[cs.length - 1], msgIndex: i };
    }
    return null;
  })();
  const latestChart: AgentChartSpec | null = latestChartInfo?.spec ?? null;

  // CR-008-C: pin charts/analyses to "Çalışma Alanım". Session-scoped dedup keyed
  // by the source message so a double-click can't create duplicates.
  const [pinnedKeys, setPinnedKeys] = useState<Set<string>>(new Set());

  const pinChart = async () => {
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
        payload: latestChartInfo.spec, // snapshot — exactly what's on screen
        source_conversation_id: activeId || null,
      });
      setPinnedKeys((prev) => new Set(prev).add(key));
      toast.success("Çalışma alanınıza eklendi");
    } catch {
      toast.error("Çalışma alanına eklenemedi");
    }
  };

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

  // CR-004-I: auto-scroll to the newest message within the chat container.
  useEffect(() => {
    if (messages.length === 0) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeId, messages.length, loading]);

  // Push a conversation to the server (fire-and-forget; cache already updated).
  const syncConversation = (id: string, title: string, msgs: Msg[], projId: string) => {
    apiPut(`/ai/conversations/${id}`, { title, messages: msgs, project_id: projId || null }).catch(() => {});
  };

  const startNewChat = () => {
    setActiveId(null);
    setInput("");
  };

  const selectConversation = (id: string) => {
    setActiveId(id);
    setProjectId(conversations.find((c) => c.id === id)?.projectId ?? "");
    setInput("");
  };

  const deleteConversation = (id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeId === id) setActiveId(null);
    apiDelete(`/ai/conversations/${id}`).catch(() => {});
  };

  const ask = async (question: string) => {
    if (!question.trim() || loading) return;
    const userMsg: Msg = { role: "user", text: question };
    const now = new Date().toISOString();

    // Append to the active conversation, or create a new one for the first message.
    const existing = activeId ? conversations.find((c) => c.id === activeId) : null;
    const id = existing ? existing.id : newId();
    const title = existing ? existing.title : question.length > 60 ? `${question.slice(0, 60)}…` : question;
    const afterUser = [...(existing?.messages ?? []), userMsg];

    if (existing) {
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages: afterUser, updatedAt: now } : c)));
    } else {
      setConversations((prev) => [{ id, title, messages: afterUser, projectId, updatedAt: now }, ...prev]);
      setActiveId(id);
    }
    // Save the user turn immediately so it survives even if the answer fails.
    syncConversation(id, title, afterUser, projectId);
    setInput("");
    setLoading(true);

    // Brief generic "thinking" animation during the request (no streaming yet, §7.2).
    let gi = 0;
    setThinkingStep(GENERIC_STEPS[0]);
    const timer = window.setInterval(() => {
      gi = (gi + 1) % GENERIC_STEPS.length;
      setThinkingStep(GENERIC_STEPS[gi]);
    }, 1100);

    try {
      // CR-007-B agent endpoint: send the full session as Anthropic messages
      // ({role:"ai"|"user", text} -> {role:"assistant"|"user", content}, §0 S2).
      // The legacy single-shot POST /ai/assistant (CR-003-H) stays available as a
      // fallback for now; plan its deprecation once the agent endpoint is stable.
      const res = await apiPost<AgentResponse>("/ai/agent", {
        messages: toAgentMessages(afterUser),
        project_id: projectId || null,
      });
      window.clearInterval(timer);

      // Short replay of the real steps the agent took, derived from tools_used.
      for (const t of res.tools_used ?? []) {
        setThinkingStep(TOOL_STEPS[t] ?? "Araç çalıştırılıyor…");
        await sleep(420);
      }

      const aiMsg: Msg = {
        role: "ai",
        text: res.answer_markdown || "Bu konuda veri bulunamadı.",
        at: res.generated_at,
        charts: res.charts ?? [],
        citations: res.citations ?? [],
        tools_used: res.tools_used ?? [],
      };
      const afterAi = [...afterUser, aiMsg];
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages: afterAi, updatedAt: new Date().toISOString() } : c)));
      syncConversation(id, title, afterAi, projectId);
    } catch (e: any) {
      window.clearInterval(timer);
      const aiMsg: Msg = { role: "ai", text: e.message ?? "AI şu an kullanılamıyor." };
      const afterAi = [...afterUser, aiMsg];
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages: afterAi, updatedAt: new Date().toISOString() } : c)));
      syncConversation(id, title, afterAi, projectId);
    } finally {
      window.clearInterval(timer);
      setLoading(false);
      setThinkingStep(null);
    }
  };

  // {role:"ai", text} -> {role:"assistant", content}; user unchanged (§0 S2).
  const toAgentMessages = (msgs: Msg[]) =>
    msgs.map((m) => ({ role: m.role === "ai" ? "assistant" : "user", content: m.text }));

  // Load the server copy on mount (authoritative — syncs across devices), then
  // run any handed-off question once the list is in place.
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

  return (
    <div>
      <PageHeader title="AI Asistan" subtitle="Finansal sorularınızı Türkçe sorun" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        <div className="lg:col-span-3">
          {/* Active conversation header + new chat */}
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="truncate text-sm font-semibold text-primary">{activeConv ? activeConv.title : "Yeni Sohbet"}</h2>
            <button
              onClick={startNewChat}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-navy-50"
            >
              <Plus className="h-3.5 w-3.5" /> Yeni Sohbet
            </button>
          </div>

          {/* Preset questions — only on an empty chat */}
          {messages.length === 0 && (
            <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {PRESETS.map((q) => (
                <button key={q} onClick={() => ask(q)} className="rounded-md border border-border bg-surface px-3 py-2 text-left text-sm hover:bg-navy-50">
                  {q}
                </button>
              ))}
            </div>
          )}

          {/* Chat — Claude-style: user in a soft bubble, AI as plain full-width text */}
          <div className="mb-3 space-y-6 overflow-y-auto rounded-xl border border-border bg-surface p-4 sm:px-6" style={{ height: "calc(100vh - 320px)" }}>
            {messages.length === 0 && <p className="text-sm text-text-secondary">Bir soru seçin veya yazın.</p>}
            {messages.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-bg px-4 py-2.5 text-sm text-text-primary">
                    {m.text}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-2 text-white">
                    <Sparkles className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1 pt-0.5 text-sm leading-relaxed text-text-primary">
                    <MarkdownText text={m.text} />
                    {/* CR-007-G: inline charts rendered from the agent's chart specs. */}
                    {(m.charts ?? []).map((spec, ci) => (
                      <AgentChart key={ci} spec={spec} />
                    ))}
                    {/* CR-007-H: citation chips — click navigates to + highlights the record. */}
                    {(m.citations ?? []).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {(m.citations ?? []).map((c) => (
                          <button
                            key={c.id}
                            onClick={() => navigate(c.deep_link)}
                            title={c.label}
                            className="inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-bg px-2.5 py-1 text-xs text-text-primary transition hover:border-brand hover:bg-navy-50"
                          >
                            <FileText className="h-3 w-3 shrink-0 text-brand" />
                            <span className="truncate">{c.label}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {m.at && <div className="mt-1.5 text-[10px] text-text-secondary">Bu yanıt {formatDateTime(m.at)} itibarıyla hesaplanmıştır</div>}
                    <div className="mt-1 flex items-center gap-3">
                      <AIDisclaimer short />
                      {/* CR-008-C: pin this answer (snapshot) to Çalışma Alanım. */}
                      <button
                        onClick={() => pinAnalysis(m, i)}
                        className="inline-flex items-center gap-1 text-[11px] font-medium text-text-secondary transition hover:text-brand"
                      >
                        <Pin className="h-3 w-3" /> Sabitle
                      </button>
                    </div>
                  </div>
                </div>
              )
            )}
            {loading && (
              <div className="flex gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-2 text-white">
                  <Sparkles className="h-4 w-4 animate-pulse" />
                </span>
                <div className="pt-1.5 text-sm text-text-secondary">{thinkingStep ?? "Yanıt hazırlanıyor…"}</div>
              </div>
            )}
            <div ref={endRef} />
          </div>

          {/* Input — Claude-style composer with an arrow send button inside the box */}
          <form className="sticky bottom-0 bg-bg py-2" onSubmit={(e) => { e.preventDefault(); ask(input); }}>
            <div className="relative flex items-center rounded-2xl border border-border bg-surface shadow-sm transition focus-within:border-brand">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Sorunuzu yazın…"
                className="w-full bg-transparent py-3 pl-4 pr-14 text-sm outline-none"
              />
              <button
                type="submit"
                disabled={loading || !input.trim()}
                aria-label="Gönder"
                className="absolute right-2 flex h-8 w-8 items-center justify-center rounded-full bg-primary text-white transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
              </button>
            </div>
          </form>
        </div>

        {/* Sidebar: Tuval (Canvas) + project filter + conversation history */}
        <div className="space-y-5">
          {/* CR-007-I Canvas panel + CR-008-C pin action. */}
          <div>
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-text-secondary">Tuval</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => navigate("/workspace")}
                  className="text-[11px] font-medium text-brand hover:underline"
                >
                  Görüntüle
                </button>
                <button
                  type="button"
                  onClick={pinChart}
                  disabled={!latestChart}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-xs font-medium text-text-primary transition hover:bg-navy-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Pin className="h-3 w-3" /> Çalışma Alanıma Ekle
                </button>
              </div>
            </div>
            {latestChart ? (
              <AgentChart spec={latestChart} height={240} />
            ) : (
              <p className="rounded-xl border border-dashed border-border bg-surface p-4 text-xs text-text-secondary">
                Bir analiz veya grafik istediğinizde burada görünecek.
              </p>
            )}
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-text-secondary">Proje Filtresi</label>
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">Tüm Projeler</option>
              {(projects ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-text-secondary">Sohbet Geçmişi</span>
              <button onClick={startNewChat} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-brand hover:bg-navy-50">
                <Plus className="h-3.5 w-3.5" /> Yeni
              </button>
            </div>
            <div className="space-y-1 overflow-y-auto pr-0.5" style={{ maxHeight: "calc(100vh - 360px)" }}>
              {conversations.length === 0 && <p className="px-1 text-xs text-text-secondary">Henüz sohbet yok.</p>}
              {conversations.map((c) => (
                <div
                  key={c.id}
                  className={`group flex items-center gap-1 rounded-md border px-2 py-1.5 transition-colors ${
                    c.id === activeId ? "border-brand bg-navy-50" : "border-border bg-surface hover:bg-navy-50"
                  }`}
                >
                  <button onClick={() => selectConversation(c.id)} className="min-w-0 flex-1 text-left">
                    <div className="truncate text-xs font-medium text-text-primary">{c.title}</div>
                    <div className="text-[10px] text-text-secondary">{formatDateTime(c.updatedAt)}</div>
                  </button>
                  <button
                    onClick={() => deleteConversation(c.id)}
                    aria-label="Sohbeti sil"
                    className="shrink-0 text-text-secondary opacity-0 transition hover:text-danger group-hover:opacity-100"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
