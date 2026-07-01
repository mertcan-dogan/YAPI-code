import { Menu, MenuItem } from "@/components/ui";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import { MoreVertical } from "lucide-react";
import { useNavigate } from "react-router-dom";

// CR-029-E §10: Reports & Decks. "Aç" routes to the real Raporlar page (where the
// existing PDF/Excel exports live); deck "Oluştur"/"Paylaş" generation is Phase 2
// → honest "yakında" toast (no fabricated file). Mini-chart thumbnails are inline
// SVG (decorative, not data).
interface ReportRow {
  title: string;
  subtitle: string;
  thumb: React.ReactNode;
  actions: { label: "Aç" | "Paylaş" | "Oluştur" }[];
}

const SOON = "Bu özellik yakında tüm kullanıcılara sunulacak.";

const BarsThumb = ({ bars }: { bars: { x: number; y: number; h: number; c: string }[] }) => (
  <svg width="48" height="34" viewBox="0 0 48 34" aria-hidden="true">
    {bars.map((b, i) => <rect key={i} x={b.x} y={b.y} width="6" height={b.h} fill={b.c} />)}
  </svg>
);
const LineThumb = ({ points, color }: { points: string; color: string }) => (
  <svg width="48" height="34" viewBox="0 0 48 34" aria-hidden="true"><polyline points={points} fill="none" stroke={color} strokeWidth="2" /></svg>
);

const ROWS: ReportRow[] = [
  { title: "Aylık Finans Sunumu", subtitle: "Mayıs 2026", thumb: <BarsThumb bars={[{ x: 5, y: 17, h: 13, c: "#2563EB" }, { x: 14, y: 10, h: 20, c: "#14B8A6" }, { x: 23, y: 21, h: 9, c: "#2563EB" }, { x: 32, y: 6, h: 24, c: "#10B981" }]} />, actions: [{ label: "Aç" }, { label: "Paylaş" }] },
  { title: "Yönetim Kurulu Nakit Akışı Özeti", subtitle: "Mayıs 2026", thumb: <LineThumb points="4,24 14,15 24,19 34,8 44,13" color="#2563EB" />, actions: [{ label: "Oluştur" }] },
  { title: "Proje Tahmin Raporu", subtitle: "Q2 2026", thumb: <LineThumb points="4,26 14,17 24,21 34,11 44,15" color="#14B8A6" />, actions: [{ label: "Oluştur" }] },
  { title: "Maliyet Sapma Analizi", subtitle: "Mayıs 2026", thumb: <BarsThumb bars={[{ x: 7, y: 13, h: 17, c: "#2563EB" }, { x: 18, y: 9, h: 21, c: "#EF4444" }, { x: 29, y: 16, h: 14, c: "#2563EB" }, { x: 40, y: 6, h: 24, c: "#EF4444" }]} />, actions: [{ label: "Aç" }, { label: "Paylaş" }] },
];

export function ReportsPanel() {
  const navigate = useNavigate();
  const onAction = (label: string) => {
    if (label === "Aç") navigate("/reports");
    else toast.info(SOON); // Paylaş / Oluştur (deck generation = Phase 2)
  };
  return (
    <div className="rounded-card border border-border bg-surface shadow-card">
      <div className="flex items-center gap-2 px-3.5 py-3">
        <span className="text-[13px] font-semibold">Raporlar &amp; Sunumlar</span>
        <button onClick={() => navigate("/reports")} className="focus-ring ml-auto text-xs font-medium text-brand hover:underline">Tümünü gör</button>
      </div>
      {ROWS.map((r, i) => (
        <div key={r.title} className={cn("flex items-center gap-2.5 px-3.5 py-2.5", i < ROWS.length - 1 && "border-b border-border")}>
          <div className="flex h-10 w-[54px] shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-surface-soft">{r.thumb}</div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-semibold">{r.title}</div>
            <div className="text-[11px] text-text-muted">{r.subtitle}</div>
          </div>
          {r.actions.map((a) => (
            <button
              key={a.label}
              onClick={() => onAction(a.label)}
              className={cn(
                "focus-ring h-7 shrink-0 rounded-sm border px-2.5 text-[11px] transition-colors",
                a.label === "Oluştur" ? "border-blue-border bg-blue-soft text-brand" : "border-border bg-surface text-text-secondary hover:bg-surface-hover"
              )}
            >
              {a.label}
            </button>
          ))}
          <Menu align="right" triggerLabel="Rapor menüsü" trigger={<MoreVertical className="h-4 w-4 text-text-faint" />}>
            {(close) => (
              <>
                <MenuItem onClick={() => { close(); navigate("/reports"); }}>Detaylar</MenuItem>
                <MenuItem onClick={() => { close(); toast.info(SOON); }}>İndir</MenuItem>
                <MenuItem onClick={() => { close(); toast.info(SOON); }}>Özelleştir</MenuItem>
              </>
            )}
          </Menu>
        </div>
      ))}
    </div>
  );
}
