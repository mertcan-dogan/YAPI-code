import { Inbox } from "lucide-react";
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
        <Inbox className="h-8 w-8 text-primary-light" />
      </div>
      <p className="text-sm text-text-secondary">{message}</p>
      {actionLabel && onAction && <Button onClick={onAction}>{actionLabel}</Button>}
    </div>
  );
}
