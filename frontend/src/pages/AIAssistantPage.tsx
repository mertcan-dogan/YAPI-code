import { AIDisclaimer, Select } from "@/components/ui";
import { PageHeader } from "@/components/layout/AppLayout";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import type { Project } from "@/types";
import { formatDateTime } from "@/utils/format";
import { ArrowUp, Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

// CR-004-I: render **bold** segments from the AI's markdown-style numbers.
function renderInline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>
  );
}

// Lightweight markdown renderer so AI replies read like the Claude chat page:
// headings, bullet lists, dividers and bold — instead of raw ## / - markers.
function renderMarkdown(text: string) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flushList = () => {
    if (!list.length) return;
    const items = list;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="my-1 list-disc space-y-1 pl-5">
        {items.map((li, i) => <li key={i}>{renderInline(li)}</li>)}
      </ul>
    );
    list = [];
  };
  lines.forEach((raw) => {
    const line = raw.trimEnd();
    const t = line.trim();
    if (!t) { flushList(); return; }
    if (/^#{1,6}\s/.test(t)) {
      flushList();
      const level = t.match(/^#+/)![0].length;
      const content = t.replace(/^#+\s/, "");
      blocks.push(
        <p key={`h-${blocks.length}`} className={`font-semibold text-primary ${level <= 2 ? "mt-3 text-[15px]" : "mt-2 text-sm"} first:mt-0`}>
          {renderInline(content)}
        </p>
      );
      return;
    }
    if (/^([-*•])\s/.test(t)) { list.push(t.replace(/^([-*•])\s/, "")); return; }
    if (/^[-—_]{3,}$/.test(t)) { flushList(); blocks.push(<hr key={`hr-${blocks.length}`} className="my-3 border-border" />); return; }
    flushList();
    blocks.push(<p key={`p-${blocks.length}`} className="my-1">{renderInline(t)}</p>);
  });
  flushList();
  return blocks;
}

const PRESETS = [
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
}

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
  const endRef = useRef<HTMLDivElement>(null);
  const location = useLocation();

  const activeConv = conversations.find((c) => c.id === activeId) ?? null;
  const messages = activeConv?.messages ?? [];

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
    try {
      const res = await apiPost<{ answer: string; generated_at: string }>("/ai/assistant", {
        question,
        project_id: projectId || null,
      });
      const aiMsg: Msg = { role: "ai", text: res.answer, at: res.generated_at };
      const afterAi = [...afterUser, aiMsg];
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages: afterAi, updatedAt: new Date().toISOString() } : c)));
      syncConversation(id, title, afterAi, projectId);
    } catch (e: any) {
      const aiMsg: Msg = { role: "ai", text: e.message ?? "AI şu an kullanılamıyor." };
      const afterAi = [...afterUser, aiMsg];
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages: afterAi, updatedAt: new Date().toISOString() } : c)));
      syncConversation(id, title, afterAi, projectId);
    } finally {
      setLoading(false);
    }
  };

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
                    <div className="space-y-0.5">{renderMarkdown(m.text)}</div>
                    {m.at && <div className="mt-1.5 text-[10px] text-text-secondary">Bu yanıt {formatDateTime(m.at)} itibarıyla hesaplanmıştır</div>}
                    <AIDisclaimer short className="mt-1" />
                  </div>
                </div>
              )
            )}
            {loading && (
              <div className="flex gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-2 text-white">
                  <Sparkles className="h-4 w-4 animate-pulse" />
                </span>
                <div className="pt-1.5 text-sm text-text-secondary">Yanıt hazırlanıyor…</div>
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

        {/* Sidebar: project filter + conversation history */}
        <div className="space-y-5">
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
