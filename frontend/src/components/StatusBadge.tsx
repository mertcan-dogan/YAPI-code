import { STATUS_LABELS } from "@/constants";

// Status Badge — colour map from Section 6.5
const STYLES: Record<string, { bg: string; text: string }> = {
  active: { bg: "#DCFCE7", text: "#166534" },
  completed: { bg: "#DBEAFE", text: "#1E40AF" },
  suspended: { bg: "#FEF9C3", text: "#854D0E" },
  cancelled: { bg: "#FEE2E2", text: "#991B1B" },
  paid: { bg: "#DCFCE7", text: "#166534" },
  unpaid: { bg: "#F1F5F9", text: "#475569" },
  overdue: { bg: "#FEE2E2", text: "#991B1B" },
  partial: { bg: "#FFEDD5", text: "#9A3412" },
  disputed: { bg: "#F5F3FF", text: "#5B21B6" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STYLES[status] ?? { bg: "#F1F5F9", text: "#475569" };
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
