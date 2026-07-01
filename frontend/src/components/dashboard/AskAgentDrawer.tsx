import { AgentAnswerBody } from "@/components/ai/AgentAnswerBody";
import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { SideDrawer } from "@/components/SideDrawer";
import { streamAgent } from "@/lib/agentStream";
import type { AgentResponse, AgentScope } from "@/types/agent";
import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

// CR-028 §3.2.1 + CR-011-D §4.1: the ask-anywhere answer in a slide-over, using
// the cited agent (POST /ai/agent) with REAL token streaming + a real-time step
// indicator (driven by stream events, not a timer), the CR-024 trust treatment,
// proposed-action Onayla/Reddet cards, and analysis export. Optionally domain-
// scoped (the scoped-agent dock passes `scope`).
const SCOPE_TITLES: Record<AgentScope, string> = {
  gider: "Gider Agent",
  gelir: "Gelir Agent",
  finans: "Finans Agent",
  hakedis: "Hakediş Agent",
  belge: "Belge Agent",
};

export function AskAgentDrawer({
  question,
  onClose,
  scope = null,
}: {
  question: string | null;
  onClose: () => void;
  scope?: AgentScope | null;
}) {
  const navigate = useNavigate();
  const [res, setRes] = useState<AgentResponse | null>(null);
  const [liveText, setLiveText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState(false);
  const [step, setStep] = useState("Soru anlaşılıyor…");

  useEffect(() => {
    if (!question) return;
    setRes(null);
    setLiveText("");
    setError(false);
    setStreaming(true);
    setStep("Soru anlaşılıyor…");

    const abort = streamAgent(
      { messages: [{ role: "user", content: question }], project_id: null, scope },
      {
        onDelta: (t) => setLiveText((prev) => prev + t),
        // A tool started: clear any preamble preview and show the real step.
        onStep: (label) => {
          setLiveText("");
          if (label) setStep(label);
        },
        onFinal: (r) => {
          setRes(r);
          setStreaming(false);
        },
        onError: () => {
          setError(true);
          setStreaming(false);
        },
      }
    );
    return () => abort();
  }, [question, scope]);

  const title = scope ? SCOPE_TITLES[scope] : "Yapı'ya soru";

  const navigateAndClose = (to: string) => {
    onClose();
    navigate(to);
  };

  return (
    <SideDrawer open={!!question} title={title} onClose={onClose}>
      {question && (
        <div className="mb-3 rounded-control bg-bg px-3 py-2 text-sm text-text-secondary">“{question}”</div>
      )}
      <AiTrustBadge compact />

      <AgentAnswerBody
        res={res}
        liveText={liveText}
        streaming={streaming}
        step={step}
        error={error}
        question={question ?? ""}
        onNavigate={navigateAndClose}
      />

      {res && (
        <button
          onClick={() => {
            onClose();
            navigate("/ai-assistant", { state: { q: question } });
          }}
          className="focus-ring mt-3 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
        >
          Tam sohbete git <ArrowRight className="h-3.5 w-3.5" />
        </button>
      )}
    </SideDrawer>
  );
}
