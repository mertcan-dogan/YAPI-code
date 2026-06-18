import { Check, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { apiPost } from "@/lib/api";
import { toast } from "@/store/toast";

interface Props {
  question: string;
  queryLogId?: string | null;
}

/**
 * CR-024-C — per-answer 👍/👎 (+ optional comment) feedback.
 *
 * Append-only: posting NEVER mutates/regenerates the answer (§0.2.4). A thumb
 * click posts the rating immediately; 👎 (or "Görüş ekle") reveals an optional
 * comment box whose "Gönder" posts a follow-up with the comment. Re-clicking the
 * same rating is guarded; a failed POST degrades to a toast (no crash). Only
 * rendered for real answers (the caller hides it on degraded/no-answer).
 */
export function AiFeedbackControl({ question, queryLogId }: Props) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [showComment, setShowComment] = useState(false);
  const [comment, setComment] = useState("");
  const [commentSent, setCommentSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const post = (r: "up" | "down", c?: string) =>
    apiPost("/ai/agent/feedback", {
      query_log_id: queryLogId ?? null,
      question,
      rating: r,
      comment: c ?? null,
    });

  const rate = async (r: "up" | "down") => {
    if (submitting || rating === r) return; // guard: never re-submit the same rating
    setSubmitting(true);
    try {
      await post(r);
      setRating(r);
      setConfirmed(true);
      if (r === "down") setShowComment(true);
    } catch {
      toast.error("Geri bildirim gönderilemedi");
    } finally {
      setSubmitting(false);
    }
  };

  const sendComment = async () => {
    const c = comment.trim();
    if (!c || submitting) return;
    setSubmitting(true);
    try {
      await post(rating ?? "down", c);
      setCommentSent(true);
      setShowComment(false);
      toast.success("Teşekkürler, geri bildiriminiz kaydedildi.");
    } catch {
      toast.error("Geri bildirim gönderilemedi");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-2 text-[11px] text-text-secondary">
      <div className="flex flex-wrap items-center gap-2">
        <span>Bu yanıt yardımcı oldu mu?</span>
        <button
          type="button"
          onClick={() => rate("up")}
          disabled={submitting}
          aria-label="Yararlı"
          aria-pressed={rating === "up"}
          title="Yararlı"
          className={cn("rounded p-1 transition hover:bg-green-50", rating === "up" && "text-success")}
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => rate("down")}
          disabled={submitting}
          aria-label="Yararsız"
          aria-pressed={rating === "down"}
          title="Yararsız"
          className={cn("rounded p-1 transition hover:bg-red-50", rating === "down" && "text-danger")}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </button>
        {confirmed && (
          <span className="inline-flex items-center gap-1 text-success">
            <Check className="h-3 w-3" /> Teşekkürler, geri bildiriminiz kaydedildi.
          </span>
        )}
        {confirmed && !showComment && !commentSent && (
          <button type="button" onClick={() => setShowComment(true)} className="font-medium text-brand hover:underline">
            Görüş ekle
          </button>
        )}
      </div>

      {showComment && !commentSent && (
        <div className="mt-1.5 flex flex-col gap-1.5 sm:flex-row sm:items-end">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Görüşünüz (isteğe bağlı)"
            rows={2}
            maxLength={2000}
            className="w-full rounded-md border border-border bg-surface px-2 py-1 text-xs outline-none focus:border-brand"
          />
          <button
            type="button"
            onClick={sendComment}
            disabled={!comment.trim() || submitting}
            className="shrink-0 rounded-md bg-primary px-3 py-1 text-xs font-medium text-white transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Gönder
          </button>
        </div>
      )}
    </div>
  );
}
