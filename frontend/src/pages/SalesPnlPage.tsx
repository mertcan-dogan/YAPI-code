import { DataTable, type Column } from "@/components/DataTable";
import { CurrencyToggle, UsdMissingNote, useShowUsd } from "@/components/currency";
import { ExportMenu, type ExportColumn } from "@/components/ExportMenu";
import { PageHeader } from "@/components/layout/AppLayout";
import { KPICard } from "@/components/KPICard";
import { SideDrawer } from "@/components/SideDrawer";
import { Badge, Button, Card, CardBody, Input, Label, SectionTitle, Select, Stat, Textarea } from "@/components/ui";
import { useFetch } from "@/hooks/useFetch";
import { apiDelete, apiPost, apiPut } from "@/lib/api";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";
import type {
  InvestmentReturn,
  LandownerLedger,
  LandownerPayment,
  Project,
  ProjectPnl,
  UnitSaleAllocation,
  UnitSalesPayload,
} from "@/types";
import { formatCurrency, formatDate, formatNumber, formatPct, formatUSD, toNumber } from "@/utils/format";
import { Banknote, Building2, Coins, Gauge, Landmark, Pencil, Percent, Plus, TrendingUp, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

// Revenue is sell-side (sales + landowner) for these models; hakediş for the rest.
const SELL_SIDE = ["kat_karsiligi", "yap_sat", "hasilat_paylasimi"];
const LANDOWNER_MODELS = ["kat_karsiligi", "hasilat_paylasimi"];
const PAYMENT_TYPES = ["Peşin", "Taksit", "Kredi"];
const DEED_STATUSES = ["Devredildi", "Beklemede"];
const OWNER_SIDE_LABELS: Record<string, string> = { yuklenici: "Yüklenici", arsa_sahibi: "Arsa Sahibi" };

// Profit green / loss red (CR-031 §5.1).
function pnlClass(v: string | number | null | undefined): string {
  return toNumber(v) < 0 ? "text-danger" : "text-success";
}

function MoneyPnl({ value }: { value: string | null }) {
  if (value === null) return <span className="text-text-disabled">—</span>;
  return <span className={cn("tabular font-medium", pnlClass(value))}>{formatCurrency(value)}</span>;
}

export default function SalesPnlPage() {
  const { id } = useParams();
  const showUsd = useShowUsd();
  const proj = useFetch<Project>(`/projects/${id}`);
  const dash = useFetch<{ pnl: ProjectPnl; investment_return: InvestmentReturn }>(`/projects/${id}/dashboard`);
  const sales = useFetch<UnitSalesPayload>(`/projects/${id}/unit-sales`);
  const ledger = useFetch<LandownerLedger>(`/projects/${id}/landowner-payments`);

  const [saleOpen, setSaleOpen] = useState(false);
  const [editingSale, setEditingSale] = useState<UnitSaleAllocation | null>(null);
  const [payOpen, setPayOpen] = useState(false);
  const [editingPay, setEditingPay] = useState<LandownerPayment | null>(null);

  const model = proj.data?.revenue_model ?? "hakedis";
  const sellSide = SELL_SIDE.includes(model);
  const showLandowner = LANDOWNER_MODELS.includes(model);
  const pnl = dash.data?.pnl;
  const ir = dash.data?.investment_return;

  const refetchAll = () => {
    sales.refetch();
    ledger.refetch();
    dash.refetch();
  };

  return (
    <div>
      <PageHeader
        breadcrumb={proj.data?.name ?? "Proje"}
        title="Satışlar & Kar/Zarar"
        subtitle="Daire satışları, arsa sahibi ödemeleri, gelir-modeli-duyarlı kar/zarar ve yatırım getirisi"
        action={
          <div className="flex items-center gap-2">
            <CurrencyToggle />
            <ExportMenu rows={sales.data?.allocations ?? []} columns={saleExportColumns} filename="satislar-kar-zarar" />
            {sellSide && (
              <Button onClick={() => { setEditingSale(null); setSaleOpen(true); }}>
                <Plus className="h-4 w-4" /> Satış Ekle
              </Button>
            )}
          </div>
        }
      />

      {/* Revenue-model awareness: hakediş projects have no sell-side editors. */}
      {!sellSide && (
        <Card className="mb-4">
          <CardBody className="flex items-start gap-3">
            <Banknote className="mt-0.5 h-5 w-5 shrink-0 text-brand" />
            <div>
              <div className="text-sm font-semibold text-primary">Gelir, Hakediş'ten geliyor</div>
              <p className="mt-0.5 text-caption text-text-secondary">
                Bu projenin gelir modeli hakediş tabanlı; daire satışı / arsa sahibi ödemesi girişi
                kapalıdır. Aşağıdaki Kar/Zarar, m² analizi ve kur-etkisi hakediş gelirine dayanır.
              </p>
            </div>
          </CardBody>
        </Card>
      )}

      {/* KPI band — revenue / cost / net / margin / IRR / ROI. */}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <KPICard label="Gelir" value={formatCurrency(pnl?.revenue_try)} valueTitle={formatCurrency(pnl?.revenue_try)}
          subtitle={showUsd ? formatUSD(pnl?.revenue_usd) : sourceLabel(pnl)} icon={Coins} accentColor="#2563EB" loading={dash.loading} />
        <KPICard label="Maliyet" value={formatCurrency(pnl?.cost_try)} valueTitle={formatCurrency(pnl?.cost_try)}
          subtitle={showUsd ? formatUSD(pnl?.cost_usd) : "Maliyet rollup (yetkili)"} icon={Banknote} accentColor="#7C3AED" loading={dash.loading} />
        <KPICard label="Net (finansman hariç)" value={formatCurrency(pnl?.net_excl_financing_try)}
          valueTitle={formatCurrency(pnl?.net_excl_financing_try)} alert={pnl && toNumber(pnl.net_excl_financing_try) < 0 ? "red" : null}
          subtitle={showUsd ? formatUSD(pnl?.net_excl_financing_usd) : "Gelir − Maliyet"} icon={TrendingUp} accentColor="#0D9488" loading={dash.loading} />
        <KPICard label="Marj" value={pnl?.margin_pct != null ? formatPct(pnl.margin_pct) : "—"}
          subtitle="Gelire göre" icon={Percent} accentColor="#F59E0B" loading={dash.loading} />
        <KPICard label="IRR (TRY)" value={ir?.irr_try_pct != null ? formatPct(ir.irr_try_pct) : "—"}
          subtitle={ir?.irr_usd_pct != null ? `USD: ${formatPct(ir.irr_usd_pct)}` : "Nakit akışına göre"} icon={Gauge} accentColor="#DB2777" loading={dash.loading} />
        <KPICard label="ROI" value={ir?.roi_pct != null ? formatPct(ir.roi_pct) : "—"}
          subtitle={ir?.duration_months != null ? `Süre: ${ir.duration_months} ay` : "Net kâr / maliyet"} icon={TrendingUp} accentColor="#16A34A" loading={dash.loading} />
      </div>

      {/* Kar/Zarar tablosu + Kur-Etkisi side by side on wide screens. */}
      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardBody>
            <SectionTitle title="Kar/Zarar Tablosu" subtitle={`Gelir kaynağı: ${sourceLabel(pnl)}`} icon={Banknote}
              right={pnl?.usd_missing_count ? <UsdMissingNote count={pnl.usd_missing_count} /> : undefined} />
            <div className="mt-3 overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-[11px] uppercase tracking-wide text-text-muted">
                    <th className="py-2 text-left font-semibold">Kalem</th>
                    <th className="py-2 text-right font-semibold">TRY</th>
                    {showUsd && <th className="py-2 text-right font-semibold">USD</th>}
                  </tr>
                </thead>
                <tbody className="tabular">
                  <PnlRow label="Gelir" tryV={pnl?.revenue_try} usdV={pnl?.revenue_usd} showUsd={showUsd} />
                  <PnlRow label="Maliyet (−)" tryV={pnl?.cost_try} usdV={pnl?.cost_usd} showUsd={showUsd} muted />
                  <PnlRow label="Finansman (−)" tryV={pnl?.financing_try} usdV={pnl?.financing_usd} showUsd={showUsd} muted />
                  <PnlRow label="Net (finansman hariç)" hint="tüm proje, bugüne kadar (satılmamış daireler dahil)" tryV={pnl?.net_excl_financing_try} usdV={pnl?.net_excl_financing_usd} showUsd={showUsd} strong colored />
                  <PnlRow label="Net (finansman dahil)" tryV={pnl?.net_incl_financing_try} usdV={pnl?.net_incl_financing_usd} showUsd={showUsd} strong colored />
                  <tr className="border-t border-border">
                    <td className="py-2 text-text-secondary">Marj %</td>
                    <td className="py-2 text-right font-semibold text-primary">{pnl?.margin_pct != null ? formatPct(pnl.margin_pct) : "—"}</td>
                    {showUsd && <td className="py-2 text-right text-text-disabled">—</td>}
                  </tr>
                </tbody>
              </table>
            </div>
            {pnl?.split && <ContractorSplit split={pnl.split} showUsd={showUsd} />}
          </CardBody>
        </Card>

        {/* Kur-Etkisi highlight (workbook's headline Güncel TL − Orijinal TL). */}
        <Card>
          <CardBody>
            <SectionTitle title="Kur Etkisi" subtitle="Orijinal TL → bugünkü kur" icon={Coins} />
            {pnl?.fx_effect.today_rate == null ? (
              <p className="mt-4 text-caption text-text-secondary">Bugünkü kur bulunamadığından kur etkisi hesaplanamadı.</p>
            ) : (
              <div className="mt-3 space-y-3">
                <Stat label="Orijinal Maliyet (TL)" value={formatCurrency(pnl.fx_effect.cost_try_original)} />
                <Stat label="Bugünkü Kurla (TL)" value={formatCurrency(pnl.fx_effect.cost_try_today)} hint={`Bugünkü kur: ${formatNumber(pnl.fx_effect.today_rate)} ₺`} />
                <div className="rounded-card border border-border bg-bg p-3">
                  <div className="overline">Kur Farkı</div>
                  <div className={cn("tabular mt-1 text-stat", pnlClass(pnl.fx_effect.fx_effect_try))}>
                    {formatCurrency(pnl.fx_effect.fx_effect_try)}
                  </div>
                  {pnl.fx_effect.fx_effect_pct != null && (
                    <div className={cn("text-caption", pnlClass(pnl.fx_effect.fx_effect_try))}>{formatPct(pnl.fx_effect.fx_effect_pct)}</div>
                  )}
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* m² Maliyet Analizi */}
      {pnl && (
        <Card className="mb-5">
          <CardBody>
            <SectionTitle title="m² Maliyet Analizi" subtitle="Brüt / net m², daire ve kat başına maliyet" icon={Gauge} />
            <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <M2Card label="Brüt m² Başına" trio={pnl.m2_analysis.per_gross_m2} sub={pnl.m2_analysis.gross_m2 ? `${formatNumber(pnl.m2_analysis.gross_m2)} m²` : null} showUsd={showUsd} />
              <M2Card label="Net m² Başına" trio={pnl.m2_analysis.per_net_m2} sub={pnl.m2_analysis.net_m2 ? `${formatNumber(pnl.m2_analysis.net_m2)} m²` : null} showUsd={showUsd} />
              <M2Card label="Daire Başına" trio={pnl.m2_analysis.per_unit} sub={pnl.m2_analysis.unit_count ? `${pnl.m2_analysis.unit_count} daire` : null} showUsd={showUsd} />
              <M2Card label="Kat Başına" trio={pnl.m2_analysis.per_floor} sub={pnl.m2_analysis.floor_count ? `${pnl.m2_analysis.floor_count} kat` : null} showUsd={showUsd} />
            </div>
          </CardBody>
        </Card>
      )}

      {/* CR-053: operator-model surfaces — efektif arsa maliyeti + planlı daire dağılımı. */}
      {sellSide && pnl && (
        <div className="mb-5 grid gap-4 lg:grid-cols-3">
          <EfektifArsaCard pnl={pnl} showUsd={showUsd} />
          <div className="lg:col-span-2">
            <PlannedSplitCard pnl={pnl} />
          </div>
        </div>
      )}

      {/* IRR/ROI yearly feed */}
      {ir && ir.yearly.length > 0 && (
        <Card className="mb-5">
          <CardBody>
            <SectionTitle title="Yıllık Nakit Akışı (IRR Beslemesi)" subtitle="Yatırım getirisi için tarihli nakit akışları" icon={TrendingUp} />
            <div className="mt-3 overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-[11px] uppercase tracking-wide text-text-muted">
                    <th className="py-2 text-left font-semibold">Yıl</th>
                    <th className="py-2 text-right font-semibold">Giriş (TL)</th>
                    <th className="py-2 text-right font-semibold">Çıkış (TL)</th>
                    <th className="py-2 text-right font-semibold">Net (TL)</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {ir.yearly.map((y) => (
                    <tr key={y.year} className="border-b border-border last:border-0">
                      <td className="py-2 font-medium text-primary">{y.year}</td>
                      <td className="py-2 text-right text-success">{formatCurrency(y.inflow_try)}</td>
                      <td className="py-2 text-right text-text-secondary">{formatCurrency(y.outflow_try)}</td>
                      <td className={cn("py-2 text-right font-medium", pnlClass(y.net_try))}>{formatCurrency(y.net_try)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}

      {/* Satış Kaydı — only for sell-side models. */}
      {sellSide && (
        <div className="mb-5">
          <div className="mb-2 flex items-center justify-between">
            <SectionTitle title="Satış Kaydı" subtitle={`Maliyet payı net m² esaslı${sales.data ? ` (${sales.data.basis === "net" ? "net" : "brüt"} m²)` : ""}`} />
          </div>
          {sales.data && sales.data.allocations.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-3">
              <SummaryChip label="Σ Satış" value={formatCurrency(sales.data.totals.sale_price_try)} />
              <SummaryChip label="Σ Maliyet Payı" value={formatCurrency(sales.data.totals.cost_try)} />
              <SummaryChip label="Σ Kar/Zarar" value={formatCurrency(sales.data.totals.pnl_try)} valueClass={pnlClass(sales.data.totals.pnl_try)} hint="yalnızca satılan dairelerin brüt karı" />
              {pnl && (
                <SummaryChip
                  label="Satılmamış daire maliyeti"
                  value={formatCurrency(toNumber(pnl.cost_try) - toNumber(sales.data.totals.cost_try))}
                  hint="proje Net'i ile satılan kar farkını açıklar"
                />
              )}
              <SummaryChip label="Adet" value={String(sales.data.totals.count)} />
              {sales.data.totals.avg_price_per_m2_try && <SummaryChip label="Ort. ₺/m²" value={formatCurrency(sales.data.totals.avg_price_per_m2_try)} />}
            </div>
          )}
          <DataTable
            dense
            columns={saleColumns(showUsd, (r) => { setEditingSale(r); setSaleOpen(true); }, (r) => onDeleteSale(id!, r, refetchAll))}
            rows={sales.data?.allocations ?? []}
            loading={sales.loading}
            error={sales.error}
            onRetry={sales.refetch}
            minWidth={980}
            emptyMessage="Henüz satış kaydı yok."
            emptyAction={{ label: "Satış Ekle", onClick: () => { setEditingSale(null); setSaleOpen(true); } }}
          />
        </div>
      )}

      {/* Arsa Sahibi Ödemeleri — only for kat karşılığı / hasılat. */}
      {showLandowner && (
        <div className="mb-5">
          <div className="mb-2 flex items-center justify-between">
            <SectionTitle title="Arsa Sahibi Ödemeleri" subtitle="Alınan katkı vs. taahhüt" icon={Landmark} />
            <Button variant="outline" onClick={() => { setEditingPay(null); setPayOpen(true); }}>
              <Plus className="h-4 w-4" /> Ödeme Ekle
            </Button>
          </div>
          {ledger.data && (
            <div className="mb-3 flex flex-wrap gap-3">
              <SummaryChip label="Σ Alınan" value={formatCurrency(ledger.data.rollup.total_try)} />
              {ledger.data.rollup.committed_total_try && <SummaryChip label="Taahhüt" value={formatCurrency(ledger.data.rollup.committed_total_try)} />}
              {ledger.data.rollup.remaining_try && <SummaryChip label="Kalan" value={formatCurrency(ledger.data.rollup.remaining_try)} />}
              {ledger.data.rollup.pct_paid && <SummaryChip label="Tamamlanma" value={formatPct(ledger.data.rollup.pct_paid)} />}
            </div>
          )}
          <DataTable
            dense
            columns={payColumns(showUsd, (r) => { setEditingPay(r); setPayOpen(true); }, (r) => onDeletePay(id!, r, refetchAll))}
            rows={ledger.data?.payments ?? []}
            loading={ledger.loading}
            error={ledger.error}
            onRetry={ledger.refetch}
            minWidth={760}
            emptyMessage="Henüz arsa sahibi ödemesi yok."
            emptyAction={{ label: "Ödeme Ekle", onClick: () => { setEditingPay(null); setPayOpen(true); } }}
          />
        </div>
      )}

      <SaleDrawer open={saleOpen} projectId={id!} editing={editingSale} onClose={() => { setSaleOpen(false); setEditingSale(null); }} onSaved={() => { setSaleOpen(false); setEditingSale(null); refetchAll(); }} />
      <PaymentDrawer open={payOpen} projectId={id!} editing={editingPay} onClose={() => { setPayOpen(false); setEditingPay(null); }} onSaved={() => { setPayOpen(false); setEditingPay(null); refetchAll(); }} />
    </div>
  );
}

function sourceLabel(pnl?: ProjectPnl): string {
  if (!pnl) return "—";
  // CR-053 operator model: sell-side revenue = the contractor's OWN sales +
  // cash landowner contributions (arsa sahibi satışları ve devredilen arsa hariç).
  return pnl.revenue_source === "sales" ? "Yüklenici satışları + nakit katkı" : "Hakediş";
}

function PnlRow({ label, hint, tryV, usdV, showUsd, muted, strong, colored }: {
  label: string; hint?: string; tryV?: string | null; usdV?: string | null; showUsd: boolean; muted?: boolean; strong?: boolean; colored?: boolean;
}) {
  return (
    <tr className="border-b border-border last:border-0">
      <td className={cn("py-2", strong ? "font-semibold text-primary" : "text-text-secondary")}>
        {label}
        {hint && <div className="text-caption font-normal text-text-muted">{hint}</div>}
      </td>
      <td className={cn("py-2 text-right", strong && "font-semibold", colored ? pnlClass(tryV) : muted ? "text-text-secondary" : "text-primary")}>
        {formatCurrency(tryV)}
      </td>
      {showUsd && <td className={cn("py-2 text-right", colored ? pnlClass(usdV) : "text-text-secondary")}>{formatUSD(usdV)}</td>}
    </tr>
  );
}

function ContractorSplit({ split, showUsd }: { split: NonNullable<ProjectPnl["split"]>; showUsd: boolean }) {
  return (
    <div className="mt-4 border-t border-border pt-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="overline">Yüklenici / Arsa Sahibi Payı</span>
        {split.contractor_share_pct && <Badge variant="info">Yüklenici %{formatNumber(split.contractor_share_pct)}</Badge>}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {([["Yüklenici", split.contractor], ["Arsa Sahibi", split.landowner]] as const).map(([label, side]) => (
          <div key={label} className="rounded-card border border-border bg-bg p-3">
            <div className="text-sm font-semibold text-primary">{label}</div>
            <div className="mt-1.5 space-y-1 text-caption text-text-secondary">
              <div className="flex justify-between"><span>Satış</span><span className="tabular text-text-primary">{formatCurrency(side.sales_try)}</span></div>
              {"payments_try" in side && <div className="flex justify-between"><span>Ödemeler</span><span className="tabular text-text-primary">{formatCurrency((side as any).payments_try)}</span></div>}
              {side.allocated_cost_try && <div className="flex justify-between"><span>Maliyet payı</span><span className="tabular text-text-primary">{formatCurrency(side.allocated_cost_try)}</span></div>}
              {showUsd && <div className="flex justify-between"><span>Satış (USD)</span><span className="tabular text-text-primary">{formatUSD(side.sales_usd)}</span></div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function M2Card({ label, trio, sub, showUsd }: { label: string; trio: { try: string | null; usd: string | null; try_today: string | null }; sub: string | null; showUsd: boolean }) {
  return (
    <div className="rounded-card border border-border bg-bg p-3">
      <div className="overline">{label}</div>
      <div className="tabular mt-1 text-stat text-primary">{trio.try != null ? formatCurrency(trio.try) : "—"}</div>
      <div className="mt-1 space-y-0.5 text-caption text-text-secondary">
        {sub && <div>{sub}</div>}
        {showUsd && trio.usd != null && <div>USD: {formatUSD(trio.usd)}</div>}
        {trio.try_today != null && <div>Bugünkü kur: {formatCurrency(trio.try_today)}</div>}
      </div>
    </div>
  );
}

function SummaryChip({ label, value, valueClass, hint }: { label: string; value: string; valueClass?: string; hint?: string }) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-2">
      <div className="overline">{label}</div>
      <div className={cn("tabular text-base font-semibold", valueClass ?? "text-primary")}>{value}</div>
      {hint && <div className="mt-0.5 text-caption text-text-muted">{hint}</div>}
    </div>
  );
}

// CR-053: Efektif Arsa Maliyeti — construction × arsa sahibi payı. DERIVED /
// informational only; it is NEVER added to revenue or cost (the land's cost is
// already embodied in the construction of the flats given to the landowner).
function EfektifArsaCard({ pnl, showUsd }: { pnl: ProjectPnl; showUsd: boolean }) {
  const tryV = pnl.efektif_arsa_maliyeti_try ?? null;
  const usdV = pnl.efektif_arsa_maliyeti_usd ?? null;
  const sharePct = pnl.landowner_share_pct ?? null;
  return (
    <Card>
      <CardBody>
        <SectionTitle title="Efektif Arsa Maliyeti" subtitle="Bilgi amaçlı — türetilmiş" icon={Landmark} />
        <div className="mt-3">
          <div className="overline">Arsanın efektif maliyeti</div>
          <div className="tabular mt-1 text-stat text-primary">{tryV != null ? formatCurrency(tryV) : "–"}</div>
          {showUsd && usdV != null && <div className="mt-0.5 text-caption text-text-secondary">USD: {formatUSD(usdV)}</div>}
        </div>
        <p className="mt-3 rounded-card border border-border bg-bg p-3 text-caption text-text-secondary">
          İnşaat maliyeti × arsa sahibi payı{sharePct != null ? ` (${formatPct(sharePct)})` : ""}. Bu tutar
          <span className="font-medium text-text-primary"> bilgi amaçlıdır</span>; gelire eklenmez ve maliyete tekrar
          yazılmaz — arsanın bedeli, arsa sahibine verilen dairelerin inşaat maliyetinin içinde zaten yer alır.
        </p>
      </CardBody>
    </Card>
  );
}

// CR-053: Planlı Daire Dağılımı — yüklenici satılabilir / arsa sahibi payı /
// satılan / kalan (projeksiyon). Degrades calmly when no schedule is entered.
function PlannedSplitCard({ pnl }: { pnl: ProjectPnl }) {
  const ps = pnl.planned_split;
  return (
    <Card className="h-full">
      <CardBody>
        <SectionTitle title="Planlı Daire Dağılımı" subtitle="Yüklenici satılabilir stok, satılan ve kalan" icon={Building2} />
        {!ps?.has_schedule ? (
          <p className="mt-4 text-caption text-text-secondary">
            Daire dağılımı girilmemiş. Konut Detayları’ndan daireleri “Yüklenici / Arsa Sahibi” olarak etiketleyin.
          </p>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <SplitStat
                label="Yüklenici (satılabilir)"
                value={`${ps.contractor.units} daire`}
                hint={`Brüt ${formatNumber(ps.contractor.gross_m2)} m² · Net ${formatNumber(ps.contractor.net_m2)} m²`}
                extra={ps.contractor.estimated_sales_try != null ? `Tahmini: ${formatCurrency(ps.contractor.estimated_sales_try)}` : null}
              />
              <SplitStat
                label="Arsa Sahibi"
                value={`${ps.landowner.units} daire`}
                hint={`Brüt ${formatNumber(ps.landowner.gross_m2)} m² · Net ${formatNumber(ps.landowner.net_m2)} m²`}
                extra={null}
              />
              <SplitStat
                label="Satılan"
                value={`${ps.sold.units} daire`}
                hint={formatCurrency(ps.sold.value_try)}
                extra={null}
              />
              <SplitStat
                label="Kalan"
                value={`${ps.remaining.units} daire`}
                hint={ps.remaining.projected_value_try != null ? `Projeksiyon: ${formatCurrency(ps.remaining.projected_value_try)}` : "Projeksiyon: –"}
                extra={null}
              />
            </div>
            <p className="mt-3 text-caption text-text-muted">
              Kalan = yüklenici satılabilir stok − satılan. Projeksiyon, kalan dairelerin planlanan satış fiyatına göredir.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function SplitStat({ label, value, hint, extra }: { label: string; value: string; hint: string; extra: string | null }) {
  return (
    <div className="rounded-card border border-border bg-bg p-3">
      <div className="overline">{label}</div>
      <div className="tabular mt-1 text-stat text-primary">{value}</div>
      <div className="mt-0.5 text-caption text-text-secondary">{hint}</div>
      {extra && <div className="text-caption text-text-secondary">{extra}</div>}
    </div>
  );
}

// --- Sales table ---
function saleColumns(showUsd: boolean, onEdit: (r: UnitSaleAllocation) => void, onDelete: (r: UnitSaleAllocation) => void): Column<UnitSaleAllocation>[] {
  return [
    { key: "unit_label", header: "Daire", render: (r) => <span className="font-medium text-primary">{r.unit_label}</span> },
    { key: "unit_type", header: "Tip", render: (r) => r.unit_type ?? "—" },
    { key: "floor", header: "Kat", render: (r) => r.floor ?? "—" },
    { key: "net_m2", header: "m²", align: "right", render: (r) => formatNumber(r.net_m2 ?? r.gross_m2 ?? 0) },
    { key: "buyer_name", header: "Alıcı", render: (r) => r.buyer_name ?? "—", maxWidth: 140 },
    { key: "sale_price_try", header: "Satış (₺)", align: "right", render: (r) => formatCurrency(r.sale_price_try) },
    ...(showUsd ? [{ key: "sale_price_usd", header: "Satış ($)", align: "right" as const, render: (r: UnitSaleAllocation) => formatUSD(r.sale_price_usd) }] : []),
    { key: "unit_cost_usd", header: "Maliyet ($)", align: "right", render: (r) => formatUSD(r.unit_cost_usd) },
    { key: "pnl_try", header: "Kar/Zarar", align: "right", render: (r) => <MoneyPnl value={r.pnl_try} /> },
    { key: "margin_pct", header: "Marj", align: "right", render: (r) => r.margin_pct != null ? <span className={cn("tabular", pnlClass(r.margin_pct))}>{formatPct(r.margin_pct)}</span> : <span className="text-text-disabled">—</span> },
    { key: "sale_date", header: "Tarih", align: "right", render: (r) => formatDate(r.sale_date), sortable: true },
    { key: "deed_status", header: "Tapu", render: (r) => r.deed_status ? <Badge variant={r.deed_status === "Devredildi" ? "success" : "neutral"}>{r.deed_status}</Badge> : <span className="text-text-disabled">—</span> },
    {
      key: "actions", header: "", render: (r) => (
        <div className="flex items-center justify-end gap-1">
          <Button variant="ghost" className="px-2 py-1" aria-label="Düzenle" onClick={(e) => { e.stopPropagation(); onEdit(r); }}><Pencil className="h-4 w-4" /></Button>
          <Button variant="ghost" className="px-2 py-1 text-text-secondary hover:text-danger" aria-label="Sil" onClick={(e) => { e.stopPropagation(); onDelete(r); }}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ),
    },
  ];
}

const saleExportColumns: ExportColumn<UnitSaleAllocation>[] = [
  { header: "Daire", value: (r) => r.unit_label },
  { header: "Tip", value: (r) => r.unit_type ?? "" },
  { header: "Kat", value: (r) => r.floor ?? "" },
  { header: "Net m²", value: (r) => (r.net_m2 != null ? Number(r.net_m2) : ""), type: "number" },
  { header: "Brüt m²", value: (r) => (r.gross_m2 != null ? Number(r.gross_m2) : ""), type: "number" },
  { header: "Alıcı", value: (r) => r.buyer_name ?? "" },
  { header: "Satış (TRY)", value: (r) => toNumber(r.sale_price_try), type: "currency" },
  { header: "Satış (USD)", value: (r) => (r.sale_price_usd != null ? Number(r.sale_price_usd) : ""), type: "usd" },
  { header: "Maliyet Payı (USD)", value: (r) => (r.unit_cost_usd != null ? Number(r.unit_cost_usd) : ""), type: "usd" },
  { header: "Kar/Zarar (TRY)", value: (r) => (r.pnl_try != null ? Number(r.pnl_try) : ""), type: "currency" },
  { header: "Marj (%)", value: (r) => (r.margin_pct != null ? Number(r.margin_pct) : ""), type: "percent" },
  { header: "Tarih", value: (r) => (r.sale_date ? formatDate(r.sale_date) : ""), type: "date" },
  { header: "Ödeme Türü", value: (r) => r.payment_type ?? "" },
  { header: "Tapu", value: (r) => r.deed_status ?? "" },
];

function payColumns(showUsd: boolean, onEdit: (r: LandownerPayment) => void, onDelete: (r: LandownerPayment) => void): Column<LandownerPayment>[] {
  return [
    { key: "payment_date", header: "Tarih", render: (r) => formatDate(r.payment_date), sortable: true },
    { key: "payer_name", header: "Ödeyen", render: (r) => r.payer_name ?? "—" },
    { key: "amount_try", header: "Tutar (₺)", align: "right", render: (r) => formatCurrency(r.amount_try) },
    ...(showUsd ? [{ key: "amount_usd", header: "Tutar ($)", align: "right" as const, render: (r: LandownerPayment) => formatUSD(r.amount_usd) }] : []),
    { key: "payment_type", header: "Tür", render: (r) => r.payment_type ?? "—" },
    { key: "description", header: "Açıklama", render: (r) => r.description ?? "—", maxWidth: 200 },
    {
      key: "actions", header: "", render: (r) => (
        <div className="flex items-center justify-end gap-1">
          <Button variant="ghost" className="px-2 py-1" aria-label="Düzenle" onClick={(e) => { e.stopPropagation(); onEdit(r); }}><Pencil className="h-4 w-4" /></Button>
          <Button variant="ghost" className="px-2 py-1 text-text-secondary hover:text-danger" aria-label="Sil" onClick={(e) => { e.stopPropagation(); onDelete(r); }}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ),
    },
  ];
}

async function onDeleteSale(projectId: string, r: UnitSaleAllocation, refetch: () => void) {
  if (!window.confirm(`"${r.unit_label}" satış kaydı silinsin mi?`)) return;
  try {
    await apiDelete(`/projects/${projectId}/unit-sales/${r.id}`);
    toast.success("Satış kaydı silindi");
    refetch();
  } catch (e: any) {
    toast.error(e.message ?? "Silinemedi");
  }
}

async function onDeletePay(projectId: string, r: LandownerPayment, refetch: () => void) {
  if (!window.confirm("Ödeme kaydı silinsin mi?")) return;
  try {
    await apiDelete(`/projects/${projectId}/landowner-payments/${r.id}`);
    toast.success("Ödeme silindi");
    refetch();
  } catch (e: any) {
    toast.error(e.message ?? "Silinemedi");
  }
}

// --- Sale drawer ---
function SaleDrawer({ open, projectId, editing, onClose, onSaved }: { open: boolean; projectId: string; editing: UnitSaleAllocation | null; onClose: () => void; onSaved: () => void }) {
  const empty = { unit_label: "", unit_type: "", floor: "", gross_m2: "", net_m2: "", buyer_name: "", sale_price_try: "", sale_date: new Date().toISOString().slice(0, 10), payment_type: "", installment_note: "", deed_status: "", deed_date: "", owner_side: "yuklenici", notes: "" };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (open && editing) {
      setForm({
        unit_label: editing.unit_label, unit_type: editing.unit_type ?? "", floor: editing.floor ?? "",
        gross_m2: editing.gross_m2 ?? "", net_m2: editing.net_m2 ?? "", buyer_name: editing.buyer_name ?? "",
        sale_price_try: editing.sale_price_try, sale_date: editing.sale_date,
        payment_type: editing.payment_type ?? "", installment_note: editing.installment_note ?? "",
        deed_status: editing.deed_status ?? "", deed_date: editing.deed_date ?? "",
        owner_side: editing.owner_side, notes: editing.notes ?? "",
      });
    } else if (open) setForm(empty);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        ...form,
        gross_m2: form.gross_m2 || null, net_m2: form.net_m2 || null, floor: form.floor || null,
        unit_type: form.unit_type || null, buyer_name: form.buyer_name || null,
        payment_type: form.payment_type || null, installment_note: form.installment_note || null,
        deed_status: form.deed_status || null, deed_date: form.deed_date || null, notes: form.notes || null,
      };
      if (editing) {
        await apiPut(`/projects/${projectId}/unit-sales/${editing.id}`, body);
        toast.success("Satış güncellendi");
      } else {
        await apiPost(`/projects/${projectId}/unit-sales`, body);
        toast.success("Satış kaydedildi");
      }
      onSaved();
    } catch (e: any) {
      toast.error(e.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  return (
    <SideDrawer open={open} title={editing ? "Satış Düzenle" : "Satış Ekle"} onClose={onClose} onSave={save} saving={saving} dirty={!!form.unit_label}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Daire No / Ad</Label><Input value={form.unit_label} onChange={(e) => set("unit_label", e.target.value)} placeholder="A-12" /></div>
          <div><Label>Tip</Label><Input value={form.unit_type} onChange={(e) => set("unit_type", e.target.value)} placeholder="3+1" /></div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div><Label>Kat</Label><Input value={form.floor} onChange={(e) => set("floor", e.target.value)} /></div>
          <div><Label>Brüt m²</Label><Input type="number" value={form.gross_m2} onChange={(e) => set("gross_m2", e.target.value)} /></div>
          <div><Label>Net m²</Label><Input type="number" value={form.net_m2} onChange={(e) => set("net_m2", e.target.value)} /></div>
        </div>
        <div><Label>Alıcı</Label><Input value={form.buyer_name} onChange={(e) => set("buyer_name", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Satış Tutarı (TRY)</Label><Input type="number" value={form.sale_price_try} onChange={(e) => set("sale_price_try", e.target.value)} /></div>
          <div><Label required>Satış Tarihi</Label><Input type="date" value={form.sale_date} onChange={(e) => set("sale_date", e.target.value)} /></div>
        </div>
        <FxNote rate={editing?.fx_rate_usd} usd={editing?.sale_price_usd} dateLabel="satış tarihindeki" />
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Ödeme Türü</Label><Select value={form.payment_type} onChange={(e) => set("payment_type", e.target.value)}><option value="">—</option>{PAYMENT_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}</Select></div>
          <div><Label>Mülkiyet Tarafı</Label><Select value={form.owner_side} onChange={(e) => set("owner_side", e.target.value)}>{Object.entries(OWNER_SIDE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Tapu Durumu</Label><Select value={form.deed_status} onChange={(e) => set("deed_status", e.target.value)}><option value="">—</option>{DEED_STATUSES.map((d) => <option key={d} value={d}>{d}</option>)}</Select></div>
          <div><Label>Tapu Tarihi</Label><Input type="date" value={form.deed_date} onChange={(e) => set("deed_date", e.target.value)} /></div>
        </div>
        <div><Label>Taksit Notu</Label><Input value={form.installment_note} onChange={(e) => set("installment_note", e.target.value)} placeholder="12 ay, ayda 50.000 ₺" /></div>
        <div><Label>Not</Label><Textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} /></div>
      </div>
    </SideDrawer>
  );
}

// --- Landowner payment drawer ---
function PaymentDrawer({ open, projectId, editing, onClose, onSaved }: { open: boolean; projectId: string; editing: LandownerPayment | null; onClose: () => void; onSaved: () => void }) {
  const empty = { payer_name: "Arsa Sahipleri", committed_total_try: "", payment_date: new Date().toISOString().slice(0, 10), amount_try: "", payment_type: "", description: "", notes: "" };
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (open && editing) {
      setForm({
        payer_name: editing.payer_name ?? "", committed_total_try: editing.committed_total_try ?? "",
        payment_date: editing.payment_date, amount_try: editing.amount_try,
        payment_type: editing.payment_type ?? "", description: editing.description ?? "", notes: editing.notes ?? "",
      });
    } else if (open) setForm(empty);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        ...form,
        payer_name: form.payer_name || null, committed_total_try: form.committed_total_try || null,
        payment_type: form.payment_type || null, description: form.description || null, notes: form.notes || null,
      };
      if (editing) {
        await apiPut(`/projects/${projectId}/landowner-payments/${editing.id}`, body);
        toast.success("Ödeme güncellendi");
      } else {
        await apiPost(`/projects/${projectId}/landowner-payments`, body);
        toast.success("Ödeme kaydedildi");
      }
      onSaved();
    } catch (e: any) {
      toast.error(e.message ?? "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  return (
    <SideDrawer open={open} title={editing ? "Ödeme Düzenle" : "Ödeme Ekle"} onClose={onClose} onSave={save} saving={saving} dirty={!!form.amount_try}>
      <div className="space-y-3">
        <div><Label>Ödeyen</Label><Input value={form.payer_name} onChange={(e) => set("payer_name", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label required>Tutar (TRY)</Label><Input type="number" value={form.amount_try} onChange={(e) => set("amount_try", e.target.value)} /></div>
          <div><Label required>Ödeme Tarihi</Label><Input type="date" value={form.payment_date} onChange={(e) => set("payment_date", e.target.value)} /></div>
        </div>
        <FxNote rate={editing?.fx_rate_usd} usd={editing?.amount_usd} dateLabel="ödeme tarihindeki" />
        <div><Label>Taahhüt Toplamı (TRY)</Label><Input type="number" value={form.committed_total_try} onChange={(e) => set("committed_total_try", e.target.value)} placeholder="Taahhüt edilen toplam katkı" /></div>
        <div><Label>Ödeme Türü</Label><Select value={form.payment_type} onChange={(e) => set("payment_type", e.target.value)}><option value="">—</option>{PAYMENT_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}</Select></div>
        <div><Label>Açıklama</Label><Input value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
        <div><Label>Not</Label><Textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} /></div>
      </div>
    </SideDrawer>
  );
}

// FX auto-fill note — USD is derived from the TCMB rate at the row's own date on
// save (CR-014 pattern). When editing, the stored snapshot is shown back.
function FxNote({ rate, usd, dateLabel }: { rate?: string | null; usd?: string | null; dateLabel: string }) {
  return (
    <div className="rounded-card border border-border bg-bg px-3 py-2 text-caption text-text-secondary">
      USD karşılığı, {dateLabel} TCMB kuruyla kaydederken otomatik hesaplanır.
      {usd != null && rate != null && (
        <span className="ml-1 text-text-primary">Mevcut: <span className="tabular">{formatUSD(usd)}</span> (kur {formatNumber(rate)} ₺).</span>
      )}
    </div>
  );
}
