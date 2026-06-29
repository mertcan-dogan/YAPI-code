import { AgentAnswerBody } from "@/components/ai/AgentAnswerBody";
import { AgentSteps, type AgentStep } from "@/components/ai/AgentSteps";
import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import type { AgentResponse } from "@/types/agent";

// CR-038 §7-A — the shared agent-MESSAGE renderer: AgentSteps (Cowork-style
// collapsible thinking) + the shared AgentAnswerBody, with an optional trust
// pill. Adopted by the Yapı AI page so its answers render through the SAME
// renderer as the dashboard drawer/rail — so CR-039's authoring cards,
// attachments and artifacts land in ONE place. The drawer/rail keep composing
// AgentAnswerBody directly; only the page wraps it here.
interface AgentMessageProps {
  // --- AgentAnswerBody contract ---
  res: AgentResponse | null;
  liveText?: string;
  streaming?: boolean;
  step?: string;
  error?: boolean;
  question: string;
  onNavigate: (to: string) => void;
  // --- AgentSteps (omit / empty steps ⇒ no step panel) ---
  steps?: AgentStep[];
  stepsRunning?: boolean;
  rowCounts?: Record<string, number>;
  toolSummaries?: Record<string, Record<string, unknown>>;
  usage?: { input_tokens: number; output_tokens: number };
  // --- chrome ---
  showTrustBadge?: boolean;
  // --- page extras (forwarded to AgentAnswerBody; default-off) ---
  onPin?: () => void;
  showDisclaimer?: boolean;
  showGeneratedAtLine?: boolean;
}

export function AgentMessage({
  res,
  liveText = "",
  streaming = false,
  step = "",
  error = false,
  question,
  onNavigate,
  steps,
  stepsRunning = false,
  rowCounts,
  toolSummaries,
  usage,
  showTrustBadge = false,
  onPin,
  showDisclaimer = false,
  showGeneratedAtLine = false,
}: AgentMessageProps) {
  return (
    <div>
      {showTrustBadge && (
        <div className="mb-2">
          <AiTrustBadge compact />
        </div>
      )}
      {steps && steps.length > 0 && (
        <AgentSteps steps={steps} running={stepsRunning} rowCounts={rowCounts} toolSummaries={toolSummaries} usage={usage} />
      )}
      <AgentAnswerBody
        res={res}
        liveText={liveText}
        streaming={streaming}
        step={step}
        error={error}
        question={question}
        onNavigate={onNavigate}
        onPin={onPin}
        showDisclaimer={showDisclaimer}
        showGeneratedAtLine={showGeneratedAtLine}
      />
    </div>
  );
}
