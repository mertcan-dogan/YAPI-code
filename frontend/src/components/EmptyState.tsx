import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { Button } from "./ui";

// Empty State — Section 6.7 (illustration + message + CTA)
export function EmptyState({
  message,
  actionLabel,
  onAction,
}: {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-navy-50">
        <Inbox className="h-8 w-8 text-brand" />
      </div>
      <p className="text-sm text-text-secondary">{message}</p>
      {actionLabel && onAction && <Button onClick={onAction}>{actionLabel}</Button>}
    </div>
  );
}

// Shown when a data load FAILS — distinct from EmptyState so a failed request is
// never mistaken for "no data". Offers a retry.
export function LoadError({
  message = "Veriler yüklenemedi. Lütfen tekrar deneyin.",
  onRetry,
}: {
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-red-50">
        <AlertTriangle className="h-8 w-8 text-danger" />
      </div>
      <p className="text-sm text-text-secondary">{message}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
          <RefreshCw className="h-4 w-4" /> Tekrar Dene
        </Button>
      )}
    </div>
  );
}
