import { cn } from "@/lib/cn";
import { useToast } from "@/store/toast";
import { CheckCircle2, Info, X, XCircle, AlertTriangle } from "lucide-react";

// Toast system — bottom-right (Section 10.3)
const STYLE = {
  success: { bg: "bg-success", Icon: CheckCircle2 },
  error: { bg: "bg-danger", Icon: XCircle },
  warning: { bg: "bg-accent", Icon: AlertTriangle },
  info: { bg: "bg-primary", Icon: Info },
} as const;

export function Toaster() {
  const { toasts, dismiss } = useToast();
  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
      {toasts.map((t) => {
        const { bg, Icon } = STYLE[t.kind];
        return (
          <div
            key={t.id}
            className={cn("flex items-center gap-2 rounded-md px-4 py-3 text-sm text-white shadow-lg", bg)}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="max-w-xs">{t.message}</span>
            {t.kind === "error" && (
              <button onClick={() => dismiss(t.id)} className="ml-2">
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
