import { AgentChart } from "@/components/charts/AgentChart";
import { AiExplainPanel } from "@/components/ai/AiExplainPanel";
import { AiFeedbackControl } from "@/components/ai/AiFeedbackControl";
import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { MarkdownText } from "@/components/MarkdownText";
import { SideDrawer } from "@/components/SideDrawer";
import { apiPost } from "@/lib/api";
import type { AgentResponse } from "@/types/agent";
import { ArrowRight, FileText, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

// CR-028 §3.2.1: the ask-anywhere answer, shown in a slide-over (not a page nav),
// using the EXISTING read-only cited agent (POST /ai/agent) + the CR-024 trust
// treatment (badge, citations, "AI nasıl çalıştı?" panel, feedback). The agent is
// read-only; this adds no new endpoint and no write. Streaming is CR-011 — we show
// the existing step indicator, not fake streaming.
const STEPS = ["Soru anlaşılıyor…", "Veriler inceleniyor…", "Analiz hazırlanıyor…"];

export function AskAgentDrawer({ question, onClose }: { question: string | null; onClose: () => void }) {
  const navigate = useNavigate();
  const [res, setRes] = useState<AgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [step, setStep] = useState(STEPS[0]);

  useEffect(() => {
    if (!question) return;
    setRes(null);
    setError(false);
    setLoading(true);
    let i = 0;
    setStep(STEPS[0]);
    const timer = window.setInterval(() => {
      i = (i + 1) % STEPS.length;
      setStep(STEPS[i]);
    }, 1100);
    apiPost<AgentResponse>("/ai/agent", { messages: [{ role: "user", content: question }], project_id: null })
      .then((r) => setRes(r))
      .catch(() => setError(true))
      .finally(() => {
        window.clearInterval(timer);
        setLoading(false);
      });
    return () => window.clearInterval(timer);
  }, [question]);

  return (
    <SideDrawer open={!!question} title="Yapı'ya soru" onClose={onClose}>
      {question && (
        <div className="mb-3 rounded-control bg-bg px-3 py-2 text-sm text-text-secondary">“{question}”</div>
      )}
      <AiTrustBadge compact />

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-text-secondary">
          <Loader2 className="h-4 w-4 animate-spin text-brand" /> {step}
        </div>
      ) : error ? (
        <p className="mt-4 text-sm text-text-secondary">
          Yapay zeka şu an kullanılamıyor. Lütfen birazdan tekrar deneyin.
        </p>
      ) : res ? (
        <div className="mt-3">
          <div className="text-sm leading-relaxed text-text-primary">
            <MarkdownText text={res.answer_markdown || "Bu konuda veri bulunamadı."} />
          </div>

          {(res.charts ?? []).map((spec, i) => (
            <AgentChart key={i} spec={spec} />
          ))}

          {(res.citations ?? []).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {res.citations.map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    onClose();
                    navigate(c.deep_link);
                  }}
                  title={c.label}
                  className="focus-ring inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-bg px-2.5 py-1 text-xs text-text-primary transition hover:border-brand hover:bg-surface-hover"
                >
                  <FileText className="h-3 w-3 shrink-0 text-brand" />
                  <span className="truncate">{c.label}</span>
                </button>
              ))}
            </div>
          )}

          {res.generated_at && (
            <AiExplainPanel
              toolsUsed={res.tools_used}
              rowCounts={res.row_counts}
              citationCount={(res.citations ?? []).length}
              generatedAt={res.generated_at}
            />
          )}

          {res.query_log_id && <AiFeedbackControl question={question ?? ""} queryLogId={res.query_log_id} />}

          {/* Secondary "open the full page" affordance (§3.2.4). */}
          <button
            onClick={() => {
              onClose();
              navigate("/ai-assistant", { state: { q: question } });
            }}
            className="focus-ring mt-3 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
          >
            Tam sohbete git <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}
    </SideDrawer>
  );
}
