import { Lock } from "lucide-react";
import { Link } from "react-router-dom";

// CR-024-B — single source of truth for the read-only trust claim (§0.2.1).
// If the agent ever gains write actions (CR-011 write-with-approval), change this
// copy to "onay ister" HERE and the claim updates everywhere it is shown.
export const TRUST_BADGE_FULL =
  "Salt-okunur · verilerinizi yalnızca okur, onayınız olmadan değişiklik yapmaz.";

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
        {compact ? "Salt-okunur" : TRUST_BADGE_FULL}
      </span>
    </Link>
  );
}
