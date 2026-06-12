import { AIDisclaimer, Button, Input, Select } from "@/components/ui";
import { PageHeader } from "@/components/layout/AppLayout";
import { useFetch } from "@/hooks/useFetch";
import { apiPost } from "@/lib/api";
import type { Project } from "@/types";
import { formatDateTime } from "@/utils/format";
import { Send, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

// CR-004-I: render **bold** segments from the AI's markdown-style numbers.
function renderRich(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>
  );
}

const PRESETS = [
  "Hangi proje en fazla para kaybetme riski taşıyor?",
  "Bu ay marj neden düştü?",
  "Hangi tedarikçinin en yüksek vadesi geçmiş borcu var?",
  "Önümüzdeki 90 günde ne kadar nakit ihtiyacımız var?",
  "Hangi maliyet kategorisi bütçesini aştı?",
  "Önce hangi hakedişi takip etmeliyiz?",
  "Bu projede geçen haftadan bu yana ne değişti?",
  "30 günden fazla vadesi geçmiş tedarikçi faturalarını göster",
  "İşveren 30 gün geç öderse nakit akışımıza etkisi ne olur?",
  "En yüksek kalan taahhüdü olan alt yüklenici hangisi?",
];

interface Msg {
  role: "user" | "ai";
  text: string;
  at?: string;
}

export default function AIAssistantPage() {
  const { data: projects } = useFetch<Project[]>("/projects");
  const [projectId, setProjectId] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  // CR-004-I: auto-scroll to the newest message instead of growing the page.
  // Skip the initial render (no messages) and scroll only within the chat
  // container so opening the page no longer jumps past the header.
  useEffect(() => {
    if (messages.length === 0) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, loading]);

  const ask = async (question: string) => {
    if (!question.trim() || loading) return;
    setMessages((m) => [...m, { role: "user", text: question }]);
    setInput("");
    setLoading(true);
    try {
      const res = await apiPost<{ answer: string; generated_at: string }>("/ai/assistant", {
        question,
        project_id: projectId || null,
      });
      setMessages((m) => [...m, { role: "ai", text: res.answer, at: res.generated_at }]);
    } catch (e: any) {
      setMessages((m) => [...m, { role: "ai", text: e.message ?? "AI şu an kullanılamıyor." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader title="AI Asistan" subtitle="Finansal sorularınızı Türkçe sorun" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        <div className="lg:col-span-3">
          {/* Preset questions */}
          <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {PRESETS.map((q) => (
              <button key={q} onClick={() => ask(q)} className="rounded-md border border-border bg-surface px-3 py-2 text-left text-sm hover:bg-navy-50">
                {q}
              </button>
            ))}
          </div>

          {/* Chat — fixed height, scrollable (CR-004-I) */}
          <div className="mb-3 space-y-3 overflow-y-auto rounded-lg border border-border bg-surface p-4" style={{ height: "calc(100vh - 320px)" }}>
            {messages.length === 0 && <p className="text-sm text-text-secondary">Bir soru seçin veya yazın.</p>}
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : ""}>
                <div className={`inline-block max-w-[85%] rounded-lg px-3 py-2 text-sm ${m.role === "user" ? "bg-primary text-white" : "bg-bg text-text-primary"}`}>
                  {m.role === "ai" && <Sparkles className="mr-1 inline h-3.5 w-3.5 text-accent" />}
                  <span className="whitespace-pre-wrap">{m.role === "ai" ? renderRich(m.text) : m.text}</span>
                  {m.at && <div className="mt-1 text-[10px] text-text-secondary">Bu yanıt {formatDateTime(m.at)} itibarıyla hesaplanmıştır</div>}
                  {m.role === "ai" && <AIDisclaimer short className="mt-1" />}
                </div>
              </div>
            ))}
            {loading && <div className="flex items-center gap-2 text-sm text-text-secondary"><Sparkles className="h-4 w-4 animate-pulse text-accent" /> Yanıt hazırlanıyor…</div>}
            <div ref={endRef} />
          </div>

          {/* Input — sticky at the bottom (CR-004-I) */}
          <form className="sticky bottom-0 flex gap-2 bg-bg py-2" onSubmit={(e) => { e.preventDefault(); ask(input); }}>
            <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Sorunuzu yazın…" />
            <Button type="submit" loading={loading}><Send className="h-4 w-4" /> Gönder</Button>
          </form>
        </div>

        {/* Project filter */}
        <div>
          <label className="mb-1 block text-sm font-medium text-text-secondary">Proje Filtresi</label>
          <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Tüm Projeler</option>
            {(projects ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </div>
      </div>
    </div>
  );
}
