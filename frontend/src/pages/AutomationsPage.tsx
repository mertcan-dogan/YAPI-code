import { EmptyState, LoadError } from "@/components/EmptyState";
import { PageHeader } from "@/components/layout/AppLayout";
import { SideDrawer } from "@/components/SideDrawer";
import { Badge, Button, Card, CardBody, Input, Label, Select, Switch } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { apiPut } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { toast } from "@/store/toast";
import { formatDateTime } from "@/utils/format";
import { CalendarClock, CheckCircle2, FileScan, History, Settings2, XCircle, Zap } from "lucide-react";
import { useState } from "react";

// CR-012-E — Otomasyonlar: the two curated templates as cards (enable toggle,
// "Yapılandır" config drawer, "Çalışma Geçmişi"). Real data from /automations.
interface LastRun {
  status: string;
  summary: Record<string, any> | null;
  started_at: string | null;
}
interface Automation {
  template_key: string;
  title: string;
  description: string;
  kind: "event" | "scheduled";
  id: string | null;
  enabled: boolean;
  config: Record<string, any>;
  last_run_at: string | null;
  next_run_at: string | null;
  last_run: LastRun | null;
}

const TEMPLATE_ICON: Record<string, typeof Zap> = {
  document_auto_file: FileScan,
  recurring_digest: CalendarClock,
};

const DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"];
const RUN_STATUS: Record<string, { label: string; variant: "success" | "warning" | "danger" | "neutral" }> = {
  success: { label: "Başarılı", variant: "success" },
  partial: { label: "Kısmi", variant: "warning" },
  error: { label: "Hata", variant: "danger" },
  skipped: { label: "Atlandı", variant: "neutral" },
};

export default function AutomationsPage() {
  const isDirector = useAuth((s) => s.user?.role === "director");
  const { data, loading, error, refetch } = useFetch<Automation[]>("/automations");
  const [configuring, setConfiguring] = useState<Automation | null>(null);
  const [historyFor, setHistoryFor] = useState<Automation | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const save = async (a: Automation, enabled: boolean, config: Record<string, any>) => {
    setBusy(a.template_key);
    try {
      await apiPut(`/automations/${a.template_key}`, { enabled, config });
      toast.success("Otomasyon güncellendi");
      refetch();
    } catch (e: any) {
      toast.error(e.message ?? "Güncellenemedi");
    } finally {
      setBusy(null);
    }
  };

  const toggle = (a: Automation, enabled: boolean) => {
    if (!isDirector) {
      toast.error("Bu işlem için yönetici yetkisi gerekli");
      return;
    }
    save(a, enabled, a.config);
  };

  if (error) return <LoadError onRetry={refetch} />;

  return (
    <div>
      <PageHeader
        title="Otomasyonlar"
        subtitle="Hazır otomasyon şablonlarını açın ve yapılandırın. Her veri yazımı onay kuyruğundan geçer."
      />

      {loading && !data ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {[0, 1].map((i) => <Card key={i}><CardBody className="h-40 animate-pulse" /></Card>)}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {(data ?? []).map((a) => {
            const Icon = TEMPLATE_ICON[a.template_key] ?? Zap;
            return (
              <Card key={a.template_key} className={a.enabled ? "ring-1 ring-brand/30" : ""}>
                <CardBody className="flex h-full flex-col gap-3">
                  <div className="flex items-start gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-navy-50 text-brand">
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-primary">{a.title}</h3>
                        <Badge variant={a.kind === "scheduled" ? "info" : "neutral"}>
                          {a.kind === "scheduled" ? "Zamanlanmış" : "Olay tabanlı"}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-text-secondary">{a.description}</p>
                    </div>
                    <Switch
                      checked={a.enabled}
                      disabled={!isDirector || busy === a.template_key}
                      onChange={(v) => toggle(a, v)}
                      label={`${a.title} otomasyonunu aç/kapat`}
                    />
                  </div>

                  <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-muted">
                    <span className={a.enabled ? "font-medium text-success" : ""}>
                      {a.enabled ? "Aktif" : "Pasif"}
                    </span>
                    {a.kind === "scheduled" && a.next_run_at && (
                      <span>Sonraki çalışma: {formatDateTime(a.next_run_at)}</span>
                    )}
                    {a.last_run?.started_at && (
                      <span>Son çalışma: {formatDateTime(a.last_run.started_at)}</span>
                    )}
                  </div>

                  <div className="flex gap-2 border-t border-border pt-3">
                    <Button
                      variant="outline"
                      className="flex-1 px-3 py-1.5 text-xs"
                      disabled={!isDirector}
                      onClick={() => setConfiguring(a)}
                    >
                      <Settings2 className="h-3.5 w-3.5" /> Yapılandır
                    </Button>
                    <Button
                      variant="ghost"
                      className="flex-1 px-3 py-1.5 text-xs"
                      onClick={() => setHistoryFor(a)}
                    >
                      <History className="h-3.5 w-3.5" /> Çalışma Geçmişi
                    </Button>
                  </div>
                </CardBody>
              </Card>
            );
          })}
        </div>
      )}

      {!loading && (data ?? []).length === 0 && (
        <EmptyState message="Henüz otomasyon şablonu yok." />
      )}

      {configuring && (
        <ConfigDrawer
          automation={configuring}
          saving={busy === configuring.template_key}
          onClose={() => setConfiguring(null)}
          onSave={async (config) => {
            await save(configuring, configuring.enabled, config);
            setConfiguring(null);
          }}
        />
      )}
      {historyFor && <HistoryDrawer automation={historyFor} onClose={() => setHistoryFor(null)} />}
    </div>
  );
}

// --- Config drawer — template-specific form. -------------------------------- #
function ConfigDrawer({
  automation,
  saving,
  onClose,
  onSave,
}: {
  automation: Automation;
  saving?: boolean;
  onClose: () => void;
  onSave: (config: Record<string, any>) => void;
}) {
  const [cfg, setCfg] = useState<Record<string, any>>({ ...automation.config });
  const set = (k: string, v: any) => setCfg((c) => ({ ...c, [k]: v }));

  return (
    <SideDrawer
      open
      title={`${automation.title} — Yapılandır`}
      onClose={onClose}
      onSave={() => onSave(cfg)}
      saving={saving}
    >
      {automation.template_key === "recurring_digest" ? (
        <div className="space-y-4">
          <div>
            <Label>Tekrar Aralığı</Label>
            <Select value={cfg.cadence ?? "weekly"} onChange={(e) => set("cadence", e.target.value)}>
              <option value="weekly">Haftalık</option>
              <option value="monthly">Aylık</option>
            </Select>
          </div>
          {cfg.cadence === "monthly" ? (
            <div>
              <Label>Ayın Günü (1-28)</Label>
              <Input
                type="number"
                min={1}
                max={28}
                value={cfg.day_of_month ?? 1}
                onChange={(e) => set("day_of_month", Number(e.target.value))}
              />
            </div>
          ) : (
            <div>
              <Label>Haftanın Günü</Label>
              <Select value={cfg.day_of_week ?? 0} onChange={(e) => set("day_of_week", Number(e.target.value))}>
                {DAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
              </Select>
            </div>
          )}
          <div>
            <Label>Saat (0-23)</Label>
            <Input
              type="number"
              min={0}
              max={23}
              value={cfg.hour ?? 8}
              onChange={(e) => set("hour", Number(e.target.value))}
            />
            <p className="mt-1 text-[11px] text-text-muted">Türkiye saati (Europe/Istanbul).</p>
          </div>
          <div className="rounded-lg border border-border bg-bg p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-text-primary">Uygulama içi bildirim</p>
                <p className="text-[11px] text-text-muted">Her zaman açık — güvenilir teslimat.</p>
              </div>
              <Switch checked disabled label="Uygulama içi bildirim" />
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
              <div>
                <p className="text-sm font-medium text-text-primary">E-posta</p>
                <p className="text-[11px] text-text-muted">
                  Doğrulanmış alan adı eklendiğinde best-effort gönderilir.
                </p>
              </div>
              <Switch
                checked={!!cfg.delivery?.email}
                onChange={(v) => set("delivery", { ...(cfg.delivery ?? { in_app: true }), in_app: true, email: v })}
                label="E-posta bildirimi"
              />
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <Label>Asgari Güven Eşiği</Label>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={Math.round((cfg.min_confidence ?? 0.75) * 100)}
                onChange={(e) => set("min_confidence", Number(e.target.value) / 100)}
                className="flex-1"
              />
              <span className="w-12 text-right text-sm font-semibold text-brand">
                %{Math.round((cfg.min_confidence ?? 0.75) * 100)}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-text-muted">
              Bu eşiğin altındaki belgeler otomatik önerilmez; elle inceleme akışına düşer.
            </p>
          </div>
          <div>
            <Label>Hedefler</Label>
            <div className="space-y-2">
              {[
                { key: "cost", label: "Gider (tedarikçi faturası)" },
                { key: "client_invoice", label: "Hakediş (müşteri faturası)" },
              ].map((d) => {
                const dests: string[] = cfg.destinations ?? ["cost", "client_invoice"];
                const on = dests.includes(d.key);
                return (
                  <label key={d.key} className="flex items-center gap-2 text-sm text-text-primary">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={(e) =>
                        set(
                          "destinations",
                          e.target.checked ? [...dests, d.key] : dests.filter((x) => x !== d.key)
                        )
                      }
                    />
                    {d.label}
                  </label>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </SideDrawer>
  );
}

// --- History drawer — recent runs from /automations/runs. ------------------- #
function HistoryDrawer({ automation, onClose }: { automation: Automation; onClose: () => void }) {
  const { data, loading } = useFetch<any[]>(`/automations/runs?template_key=${automation.template_key}`);
  return (
    <SideDrawer open title={`${automation.title} — Çalışma Geçmişi`} onClose={onClose}>
      {loading ? (
        <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-bg" />)}</div>
      ) : (data ?? []).length === 0 ? (
        <EmptyState message="Henüz çalışma kaydı yok." />
      ) : (
        <ul className="space-y-2">
          {(data ?? []).map((r) => {
            const st = RUN_STATUS[r.status] ?? RUN_STATUS.skipped;
            const s = r.summary ?? {};
            const detail =
              automation.template_key === "recurring_digest"
                ? `${s.notifications ?? 0} bildirim${s.emails ? ` · ${s.emails} e-posta` : ""}`
                : Object.entries(s).map(([k, v]) => `${k}: ${v}`).join(" · ");
            return (
              <li key={r.id} className="rounded-lg border border-border bg-surface p-3">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-sm font-medium text-text-primary">
                    {r.status === "error" ? (
                      <XCircle className="h-4 w-4 text-danger" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4 text-success" />
                    )}
                    {r.started_at ? formatDateTime(r.started_at) : "—"}
                  </span>
                  <Badge variant={st.variant}>{st.label}</Badge>
                </div>
                {detail && <p className="mt-1 text-xs text-text-secondary">{detail}</p>}
                {r.error && <p className="mt-1 text-xs text-danger">{r.error}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </SideDrawer>
  );
}
