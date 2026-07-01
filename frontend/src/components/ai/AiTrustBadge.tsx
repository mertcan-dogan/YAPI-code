import { Lock } from "lucide-react";
import { Link } from "react-router-dom";

// CR-024-B / CR-011-D §4.1 — single source of truth for the agent trust claim
// (§0.2.1, §0.2.2). Now that the agent can PROPOSE writes (CR-011-C), the claim
// flipped from "salt-okunur" to "önerir, siz onaylarsınız": the agent never
// writes directly — every change is a proposal a human approves. One edit here
// updates the claim everywhere it is shown.
export const TRUST_BADGE_FULL =
  "Önerir, siz onaylarsınız · onaysız hiçbir şey yazmaz — her değişiklik onayınızdan geçer.";
export const TRUST_BADGE_COMPACT = "Önerir, siz onaylarsınız";

/**
 * Always-visible trust pill shown on every agent surface. Links to the AI
 * principles page. The full claim is always available as the title/tooltip, even
 * in the compact (rail) form.
 */
export function AiTrustBadge({ compact = false, className = "" }: { compact?: boolean; className?: string }) {
  return (
    <Link
      to="/ai-principles"
      title={TRUST_BADGE_FULL}
      aria-label={TRUST_BADGE_FULL}
      className={
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-bg px-2.5 py-1 text-[11px] font-medium text-text-secondary transition hover:border-brand hover:text-brand " +
        className
      }
    >
      <Lock className="h-3 w-3 shrink-0 text-brand" />
      <span className={compact ? "" : "truncate"}>
        {compact ? TRUST_BADGE_COMPACT : TRUST_BADGE_FULL}
      </span>
    </Link>
  );
}
