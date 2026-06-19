import { apiPut } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import type { ProposedAction } from "@/types/agent";
import { Check, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

// CR-011-D §4.1 — proposed-action confirm UI. When the agent proposes a write it
// appears as a clearly-labeled "Yapı AI şunu öneriyor: …" card with Onayla /
// Reddet that route through the EXISTING /approvals flow — never an instant
// write. Only a director can decide (matching the approvals endpoints); other
// users see a link to the Onaylar page. Confirmation toast on approve.
type Decision = "pending" | "approved" | "rejected";

export function ProposedActionCard({ action }: { action: ProposedAction }) {
  const { user } = useAuth();
  const isDirector = user?.role === "director";
  const [state, setState] = useState<Decision>("pending");
  const [busy, setBusy] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [reason, setReason] = useState("");

  const approve = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await apiPut(`/approvals/request/${action.request_id}/approve`, {});
      setState("approved");
      toast.success("Öneri onaylandı ve uygulandı.");
    } catch (e: any) {
      toast.error(e?.message ?? "Onaylanamadı");
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    const r = reason.trim();
    if (!r) {
      toast.error("Red nedeni zorunludur");
      return;
    }
    setBusy(true);
    try {
      await apiPut(`/approvals/request/${action.request_id}/reject`, { reason: r });
      setState("rejected");
      setShowReject(false);
      toast.success("Öneri reddedildi.");
    } catch (e: any) {
      toast.error(e?.message ?? "Reddedilemedi");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 rounded-control border border-brand/40 bg-navy-50/60 p-3">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 text-white">
          <Sparkles className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-primary">
            Yapı AI şunu öneriyor
            <span className="ml-1 font-normal text-text-secondary">· {action.kind_label}</span>
          </p>
          <p className="mt-0.5 break-words text-[13px] text-text-primary">{action.description}</p>

          {state === "approved" ? (
            <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-success">
              <Check className="h-3.5 w-3.5" /> Onaylandı ve uygulandı.
            </p>
          ) : state === "rejected" ? (
            <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-danger">
              <X className="h-3.5 w-3.5" /> Reddedildi.
            </p>
          ) : isDirector ? (
            <>
              {!showReject ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    onClick={approve}
                    disabled={busy}
                    className="focus-ring rounded-control bg-brand px-3 py-1 text-xs font-medium text-white transition hover:bg-brand/90 disabled:opacity-50"
                  >
                    Onayla
                  </button>
                  <button
                    onClick={() => setShowReject(true)}
                    disabled={busy}
                    className="focus-ring rounded-control border border-border px-3 py-1 text-xs font-medium text-text-primary transition hover:border-danger hover:text-danger disabled:opacity-50"
                  >
                    Reddet
                  </button>
                  <span className="self-center text-[11px] text-text-faint">
                    Onaylamadan hiçbir değişiklik yapılmaz.
                  </span>
                </div>
              ) : (
                <div className="mt-2 flex flex-col gap-1.5">
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Red nedeni"
                    rows={2}
                    className="w-full rounded-md border border-border bg-surface px-2 py-1 text-xs outline-none focus:border-brand"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={reject}
                      disabled={busy || !reason.trim()}
                      className="focus-ring rounded-control bg-danger px-3 py-1 text-xs font-medium text-white transition hover:bg-danger/90 disabled:opacity-50"
                    >
                      Reddet
                    </button>
                    <button
                      onClick={() => setShowReject(false)}
                      disabled={busy}
                      className="focus-ring rounded-control border border-border px-3 py-1 text-xs font-medium text-text-primary"
                    >
                      Vazgeç
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="mt-2 text-[11px] text-text-secondary">
              Bu öneri bir yöneticinin onayını bekliyor —{" "}
              <Link to="/approvals" className="font-medium text-brand hover:underline">
                Onaylar sayfası
              </Link>
              .
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
