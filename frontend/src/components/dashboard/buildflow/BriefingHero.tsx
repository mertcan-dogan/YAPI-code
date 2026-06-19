import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { AIDisclaimer, Skeleton } from "@/components/ui";
import { ArrowRight, Info, Sparkles } from "lucide-react";
import { WaveBackground } from "./WaveBackground";

export interface RiskChips {
  kritik: number;
  izle: number;
  firsat: number;
  hazir: number;
}

// CR-029-C §6: AI Financial Briefing hero. Body = a composed Turkish summary from
// REAL dashboard data + the cached daily-briefing (no fresh agent call). Right =
// the animated wave. Four floating risk chips with connector lines (mockup
// positions/colors). Read-only trust treatment (CR-024).
const CHIPS: { key: keyof RiskChips; label: string; color: string; style: React.CSSProperties }[] = [
  { key: "kritik", label: "Kritik", color: "var(--color-danger)", style: { top: 34, right: 410 } },
  { key: "izle", label: "İzle", color: "var(--color-warning)", style: { top: 96, right: 288 } },
  { key: "firsat", label: "Fırsat", color: "var(--color-success)", style: { top: 26, right: 165 } },
  { key: "hazir", label: "İncelemeye Hazır", color: "var(--color-brand)", style: { top: 90, right: 24 } },
];

export function BriefingHero({
  text,
  loading,
  error,
  chips,
  onDetail,
  onInfo,
}: {
  text: string;
  loading?: boolean;
  error?: boolean;
  chips: RiskChips;
  onDetail?: () => void;
  onInfo?: () => void;
}) {
  return (
    <div className="relative min-h-[160px] overflow-hidden rounded-card border border-border shadow-lg" style={{ background: "linear-gradient(180deg,#FFFFFF 0%,#F8FBFF 100%)" }}>
      <WaveBackground className="pointer-events-none absolute bottom-0 right-0 top-0 z-[1] w-[62%]" />

      <button onClick={onInfo} aria-label="Bu brifing nasıl üretildi?" className="focus-ring absolute right-3.5 top-3 z-[3] text-text-faint hover:text-text-secondary">
        <Info className="h-4 w-4" />
      </button>

      <div className="relative z-[2] max-w-[560px] p-4 sm:p-[18px]">
        <div className="mb-2.5 flex items-center gap-2 text-[15px] font-semibold sm:text-base">
          <Sparkles className="h-[18px] w-[18px] text-brand" />
          Yapı AI Brifingi
        </div>
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-3 w-[90%]" />
            <Skeleton className="h-3 w-[80%]" />
            <Skeleton className="h-3 w-[60%]" />
          </div>
        ) : error ? (
          <p className="text-xs leading-relaxed text-text-secondary">Brifing şu an yüklenemedi.</p>
        ) : (
          <p className="text-xs leading-relaxed text-[#334155]">{text}</p>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <AiTrustBadge compact />
          {onDetail && (
            <button onClick={onDetail} className="focus-ring inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
              Detaylı brifing <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <AIDisclaimer short className="max-w-[520px]" />
      </div>

      {/* Risk chips — desktop only (absolute positions assume the wide hero). */}
      <div className="pointer-events-none absolute inset-0 z-[3] hidden xl:block">
        {CHIPS.map((c) => (
          <div
            key={c.key}
            className="absolute rounded-lg border border-border bg-surface px-[11px] py-[7px] text-center shadow-pop"
            style={c.style}
          >
            <div className="text-[10px] font-semibold" style={{ color: c.color }}>{c.label}</div>
            <div className="text-[15px] font-semibold leading-tight tabular">{chips[c.key]}</div>
            <span className="absolute left-1/2 top-full h-[18px] w-px opacity-50" style={{ background: c.color }} />
          </div>
        ))}
      </div>
    </div>
  );
}
