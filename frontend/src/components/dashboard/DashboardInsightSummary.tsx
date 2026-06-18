import { AiTrustBadge } from "@/components/ai/AiTrustBadge";
import { AIDisclaimer, Card, CardBody, SectionTitle, Skeleton } from "@/components/ui";
import { InsightItem, type BriefingItem } from "./InsightItem";

// CR-028 §3.2.2: inline AI summary with the read-only trust treatment, sourced
// from the EXISTING daily-briefing already fetched/cached by the page (NO fresh
// agent call per load). The briefing carries no citation records, so — honestly —
// no citation chips are shown; "Tümünü gör" opens the existing priority drawer.
export function DashboardInsightSummary({
  briefing,
  state,
  onSeeAll,
}: {
  briefing: BriefingItem[];
  state: "loading" | "ready" | "error";
  onSeeAll?: () => void;
}) {
  const top = briefing.slice(0, 3);
  return (
    <Card className="mb-4">
      <CardBody>
        <SectionTitle
          title="Portföyde dikkat edilmesi gerekenler"
          right={
            onSeeAll && (
              <button onClick={onSeeAll} className="focus-ring text-xs font-medium text-brand hover:underline">
                Tümünü gör →
              </button>
            )
          }
        />
        <div className="mt-1">
          <AiTrustBadge compact />
        </div>
        <div className="mt-2">
          {state === "loading" ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : state === "error" ? (
            <p className="text-sm text-text-secondary">Özet şu an yüklenemedi.</p>
          ) : top.length === 0 ? (
            <p className="text-sm text-text-secondary">Şu an öne çıkan bir konu yok. 👍</p>
          ) : (
            top.map((item, i) => <InsightItem key={i} item={item} />)
          )}
        </div>
        <AIDisclaimer short />
      </CardBody>
    </Card>
  );
}
