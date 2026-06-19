import { cn } from "@/lib/cn";
import * as React from "react";
import { ChevronLeft, ChevronRight, Info, Loader2, X } from "lucide-react";

// --- Button ---
type ButtonVariant = "primary" | "ghost" | "danger" | "outline";
export function Button({
  variant = "primary",
  loading = false,
  className,
  children,
  disabled,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean }) {
  const variants: Record<ButtonVariant, string> = {
    primary: "bg-primary text-white hover:bg-primary-light",
    ghost: "bg-transparent text-text-secondary hover:bg-bg",
    danger: "bg-danger text-white hover:opacity-90",
    outline: "border border-border bg-surface text-text-primary hover:bg-bg",
  };
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none",
        variants[variant],
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

// --- Card --- (CR-028: hairline border + soft shadow-card, flat & crisp)
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-card border border-border bg-surface shadow-card", className)} {...props} />;
}
export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...props} />;
}

// --- Badge (CR-028) — semantic pill for statuses/tags. The single source of
// truth for pill shape; StatusBadge composes this. `style` overrides colors. ---
type BadgeVariant = "neutral" | "info" | "success" | "warning" | "danger";
export function Badge({
  variant = "neutral",
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  const variants: Record<BadgeVariant, string> = {
    neutral: "bg-bg text-text-secondary",
    info: "bg-navy-50 text-brand",
    success: "bg-green-50 text-success",
    warning: "bg-amber-50 text-warning",
    danger: "bg-red-50 text-danger",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        variants[variant],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}

// --- Overline (CR-028) — small muted uppercase label (field/column/section). ---
export function Overline({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("overline", className)} {...props} />;
}

// --- SectionTitle (CR-028) — title + optional subtitle + right slot. ---
export function SectionTitle({
  title,
  subtitle,
  right,
  icon: Icon,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  right?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-section text-primary">
          {Icon && <Icon className="h-3.5 w-3.5 text-brand" />}
          <span>{title}</span>
        </h2>
        {subtitle && <p className="mt-0.5 text-caption leading-snug text-text-secondary">{subtitle}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}

// --- Stat / Metric (CR-028) — inline metric block (big .tabular value + muted
// overline label + optional delta in green/red). KPICard remains the richer
// dashboard *card* (icon + sparkline + click); Stat is the lightweight sibling. ---
export function Stat({
  label,
  value,
  valueTitle,
  hint,
  delta,
  className,
}: {
  label: string;
  value: React.ReactNode;
  valueTitle?: string;
  hint?: React.ReactNode;
  delta?: { text: string; positive?: boolean } | null;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="overline">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span title={valueTitle} className="tabular whitespace-nowrap text-stat text-primary">{value}</span>
        {delta && (
          <span className={cn("tabular text-xs font-medium", delta.positive ? "text-success" : "text-danger")}>{delta.text}</span>
        )}
      </div>
      {hint && <div className="mt-0.5 text-caption text-text-secondary">{hint}</div>}
    </div>
  );
}

// --- Toolbar (CR-028) — consistent filter/action bar (replaces per-page ad-hoc). ---
export function Toolbar({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-wrap items-center gap-2", className)} {...props} />;
}
export function ToolbarSpacer() {
  return <div className="flex-1" />;
}

// --- Tabs (CR-028) — accessible, keyboard-navigable (←/→). ---
export interface TabItem {
  id: string;
  label: React.ReactNode;
}
export function Tabs({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: TabItem[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  const onKey = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === value);
    if (e.key === "ArrowRight") {
      e.preventDefault();
      onChange(tabs[(i + 1) % tabs.length].id);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      onChange(tabs[(i - 1 + tabs.length) % tabs.length].id);
    }
  };
  return (
    <div role="tablist" className={cn("flex flex-wrap items-center gap-1", className)} onKeyDown={onKey}>
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cn(
              "focus-ring rounded-control px-3 py-1.5 text-sm font-medium transition-colors",
              active ? "bg-brand text-white" : "bg-surface text-text-secondary hover:bg-surface-hover"
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

// --- Input / Label / Textarea / Select ---
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { error?: boolean }>(
  ({ className, error, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "w-full rounded-md border bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand",
        error ? "border-danger" : "border-border",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn("w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand", className)}
      {...props}
    />
  )
);
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn("w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand", className)}
      {...props}
    >
      {children}
    </select>
  )
);
Select.displayName = "Select";

export function Label({
  required,
  className,
  children,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement> & { required?: boolean }) {
  return (
    <label className={cn("mb-1 block text-[13px] font-medium text-text-secondary", className)} {...props}>
      {children}
      {required && <span className="text-danger"> *</span>}
    </label>
  );
}

export function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-xs text-danger">{message}</p>;
}

// --- Checkbox (CR-001-E) ---
export function Checkbox({
  checked,
  onChange,
  label,
  id,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: React.ReactNode;
  id?: string;
}) {
  return (
    <label htmlFor={id} className="flex cursor-pointer items-center gap-2 text-sm">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[var(--color-primary)]"
      />
      {label}
    </label>
  );
}

// --- Skeleton (Section 6.7) ---
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4 w-full", className)} />;
}

// --- Modal (CR-004-D / CR-004-K) — centred overlay dialog ---
export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  size = "lg",
}: {
  open: boolean;
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: "md" | "lg" | "xl";
}) {
  if (!open) return null;
  const widths: Record<string, string> = { md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className={cn("relative z-10 my-4 w-full rounded-xl bg-surface shadow-xl animate-slide-in", widths[size])}>
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-base font-semibold text-primary">{title}</h3>
          <button onClick={onClose} className="text-text-secondary hover:text-text-primary" aria-label="Kapat">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

// --- AI Disclaimer (CR-004-F) — shown under every AI-generated output ---
export function AIDisclaimer({ short = false, className }: { short?: boolean; className?: string }) {
  const text = short
    ? "Bu yanıt yapay zeka tarafından oluşturulmuştur ve hatalar içerebilir."
    : "Bu içerik yapay zeka tarafından oluşturulmuştur ve hatalar içerebilir. Önemli finansal kararlar almadan önce lütfen doğrulayın.";
  return (
    <p className={cn("mt-2 flex items-start gap-1 text-[11px] italic", className)} style={{ color: "#94A3B8" }}>
      <Info className="mt-0.5 h-3 w-3 shrink-0" />
      <span>{text}</span>
    </p>
  );
}

// --- Menu / Dropdown (CR-029) — accessible popover for header dropdowns + the
// card three-dot menus. Click-outside + Escape close; keyboard focusable. ---
export function Menu({
  trigger,
  triggerClassName,
  triggerLabel,
  align = "right",
  width,
  children,
}: {
  trigger: React.ReactNode;
  triggerClassName?: string;
  triggerLabel?: string; // aria-label for icon-only triggers
  align?: "left" | "right";
  width?: number;
  children: React.ReactNode | ((close: () => void) => React.ReactNode);
}) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const close = () => setOpen(false);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={triggerLabel}
        onClick={() => setOpen((o) => !o)}
        className={cn("focus-ring", triggerClassName)}
      >
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          style={width ? { width } : undefined}
          className={cn(
            "absolute z-50 mt-1 min-w-[180px] overflow-hidden rounded-control border border-border bg-surface py-1 shadow-pop animate-fade-in",
            align === "right" ? "right-0" : "left-0"
          )}
        >
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </div>
  );
}

export function MenuItem({
  icon: Icon,
  children,
  onClick,
  danger,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  onClick?: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-surface-hover",
        danger ? "text-danger" : "text-text-primary"
      )}
    >
      {Icon && <Icon className="h-4 w-4 shrink-0 text-text-muted" />}
      {children}
    </button>
  );
}

// --- Sparkline (CR-029) — KPI mini-chart (mockup spark() port). ---
export function Sparkline({
  data,
  color = "var(--color-brand)",
  className,
  width = 120,
  height = 26,
}: {
  data: number[];
  color?: string;
  className?: string;
  width?: number;
  height?: number;
}) {
  if (!data || data.length < 2) return null;
  const mn = Math.min(...data);
  const mx = Math.max(...data);
  const rg = mx - mn || 1;
  const pts = data.map((d, i) => [(i / (data.length - 1)) * width, height - 2 - ((d - mn) / rg) * (height - 4)]);
  const line = pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `0,${height} ${line} ${width},${height}`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className={className} aria-hidden="true">
      <polygon points={area} fill={color} opacity={0.08} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
    </svg>
  );
}

// --- Switch / Toggle (CR-029) — iOS-style. ---
export function Switch({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange?: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={cn(
        "focus-ring relative h-[16px] w-[28px] shrink-0 rounded-full transition-colors",
        checked ? "bg-success" : "bg-border-strong",
        disabled && "cursor-not-allowed opacity-60"
      )}
    >
      <span
        className={cn(
          "absolute top-[2px] h-[12px] w-[12px] rounded-full bg-white shadow-sm transition-all",
          checked ? "left-[14px]" : "left-[2px]"
        )}
      />
    </button>
  );
}

// --- Pagination (CR-029) — prev/next arrows, disabled at ends. ---
export function Pagination({
  page,
  pageCount,
  onPage,
  className,
}: {
  page: number;
  pageCount: number;
  onPage: (p: number) => void;
  className?: string;
}) {
  const btn =
    "focus-ring flex h-[26px] w-[26px] items-center justify-center rounded-sm border border-border bg-surface text-text-secondary transition-colors hover:bg-surface-hover disabled:pointer-events-none disabled:opacity-40";
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <button type="button" aria-label="Önceki" disabled={page <= 1} onClick={() => onPage(page - 1)} className={btn}>
        <ChevronLeft className="h-3.5 w-3.5" />
      </button>
      <button type="button" aria-label="Sonraki" disabled={page >= pageCount} onClick={() => onPage(page + 1)} className={btn}>
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// --- Avatar (CR-029) — initials or photo. ---
export function Avatar({
  name,
  src,
  size = 34,
  className,
}: {
  name?: string;
  src?: string | null;
  size?: number;
  className?: string;
}) {
  const initials =
    (name || "")
      .split(" ")
      .map((w) => w[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toLocaleUpperCase("tr") || "?";
  if (src) {
    return <img src={src} alt={name ?? ""} className={cn("rounded-full object-cover", className)} style={{ width: size, height: size }} />;
  }
  return (
    <span
      className={cn("inline-flex items-center justify-center rounded-full bg-gradient-to-br from-brand to-purple font-semibold text-white", className)}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }}
    >
      {initials}
    </span>
  );
}
