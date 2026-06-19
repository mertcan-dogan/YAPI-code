import { AgentChart } from "@/components/charts/AgentChart";
import { AiExplainPanel } from "@/components/ai/AiExplainPanel";
import { AiFeedbackControl } from "@/components/ai/AiFeedbackControl";
import { AnalysisExportButton } from "@/components/ai/AnalysisExportButton";
import { ProposedActionCard } from "@/components/ai/ProposedActionCard";
import { MarkdownText } from "@/components/MarkdownText";
import type { AgentResponse } from "@/types/agent";
import { FileText, Loader2 } from "lucide-react";

// CR-011-D §4.1 — the shared agent-answer renderer used by the ask drawer and the
// rail. Streams live tokens with a real-time step indicator, then renders the
// final answer: markdown + chart(s) + citation chips + proposed-action cards +
// export + the CR-024 "AI nasıl çalıştı?" panel + feedback.
interface Props {
  res: AgentResponse | null;
  liveText: string;
  streaming: boolean;
  step: string;
  error: boolean;
  question: string;
  onNavigate: (to: string) => void;
}

export function AgentAnswerBody({ res, liveText, streaming, step, error, question, onNavigate }: Props) {
  if (error) {
    return (
      <p className="mt-4 text-sm text-text-secondary">
        Yapay zeka şu an kullanılamıyor. Lütfen birazdan tekrar deneyin.
      </p>
    );
  }

  // Final answer present → full treatment.
  if (res) {
    const citations = res.citations ?? [];
    const proposed = res.proposed_actions ?? [];
    const hasAnswer = !!(res.answer_markdown || "").trim();
    return (
      <div className="mt-3">
        <div className="text-sm leading-relaxed text-text-primary">
          <MarkdownText text={res.answer_markdown || "Bu konuda veri bulunamadı."} />
        </div>

        {(res.charts ?? []).map((spec, i) => (
          <AgentChart key={i} spec={spec} />
        ))}

        {citations.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {citations.map((c) => (
              <button
                key={c.id}
                onClick={() => onNavigate(c.deep_link)}
                title={c.label}
                className="focus-ring inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-bg px-2.5 py-1 text-xs text-text-primary transition hover:border-brand hover:bg-surface-hover"
              >
                <FileText className="h-3 w-3 shrink-0 text-brand" />
                <span className="truncate">{c.label}</span>
              </button>
            ))}
          </div>
        )}

        {/* CR-011-C — pending approval proposals as Onayla/Reddet cards. */}
        {proposed.map((a) => (
          <ProposedActionCard key={a.request_id} action={a} />
        ))}

        {/* CR-011-D — export this analysis (only meaningful with a real answer). */}
        {hasAnswer && <AnalysisExportButton res={res} question={question} />}

        {res.generated_at && (
          <AiExplainPanel
            toolsUsed={res.tools_used}
            rowCounts={res.row_counts}
            citationCount={citations.length}
            generatedAt={res.generated_at}
          />
        )}

        {res.query_log_id && <AiFeedbackControl question={question} queryLogId={res.query_log_id} />}
      </div>
    );
  }

  // Streaming with live tokens → show them as they arrive + the step indicator.
  if (liveText) {
    return (
      <div className="mt-3">
        <div className="text-sm leading-relaxed text-text-primary">
          <MarkdownText text={liveText} />
        </div>
        <div className="mt-2 flex items-center gap-2 text-xs text-text-secondary">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-brand" /> {step || "Yanıt yazılıyor…"}
        </div>
      </div>
    );
  }

  // Streaming, no tokens yet → just the real-time step indicator.
  if (streaming) {
    return (
      <div className="mt-4 flex items-center gap-2 text-sm text-text-secondary">
        <Loader2 className="h-4 w-4 animate-spin text-brand" /> {step || "Soru anlaşılıyor…"}
      </div>
    );
  }

  return null;
}
