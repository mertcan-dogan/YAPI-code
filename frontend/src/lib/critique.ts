// CR-056 — plan critique (ask-with-options), the client-side half.
//
// The agent NEVER auto-changes the plan. The backend attaches STRUCTURAL findings
// (duplicate / mislabel) on the proposed_action's `critique[]`; here we (a) detect
// the DATA-AWARE findings for free from the MiniReportPreview run-results the card
// already fetched (empty_dimension / single_row / identical_data — no extra
// /studio/run), (b) turn every finding into deterministic option BUTTONS, and (c)
// apply the chosen option to the in-memory draft widget list. Nothing changes until
// the user clicks; then Oluştur/Kaydet creates the ADJUSTED plan.
import type { RunResult, StudioSpec } from "@/types/studio";

export type FindingType =
  | "duplicate"
  | "mislabel"
  | "empty_dimension"
  | "single_row"
  | "identical_data";

export interface Finding {
  type: FindingType;
  widget_ids: string[];
  message: string;
}

// One editable draft widget. `key` matches the MiniReportPreview key (a widget id,
// or "report" for a single report) and the finding.widget_ids. `raw` is the original
// full widget object (dashboard/skill) preserved for create; null for a report.
export interface DraftWidget {
  key: string;
  title: string | null;
  spec: StudioSpec | null;
  raw: any | null;
}

export type OptionAction =
  | { kind: "keep_all" }
  | { kind: "remove"; key: string }
  | { kind: "keep_only"; key: string; among: string[] }
  | { kind: "retitle"; key: string };

export interface CritiqueOption {
  label: string;
  action: OptionAction;
}

const NL_UNSET = "(belirtilmemiş)";

// A stable id so a resolved finding stays hidden and its badges clear.
export function findingId(f: Finding): string {
  return `${f.type}:${[...f.widget_ids].sort().join(",")}`;
}

// Strip a "%" / "(%)" label from a mislabeled title (retitle resolution). Drops a
// trailing "(%)"/"( % )" group, a stray "%", and the word "yüzde", then tidies
// leftover empty parens and double spaces.
export function stripPercentLabel(title: string | null | undefined): string {
  let t = String(title ?? "");
  t = t.replace(/\(\s*%\s*\)/g, " "); // "(%)" / "( % )"
  t = t.replace(/%/g, " ");
  t = t.replace(/\byüzde\b/gi, " ");
  t = t.replace(/\(\s*\)/g, " "); // empty parens left behind
  t = t.replace(/\s+/g, " ").trim();
  return t;
}

// Mirror of the backend structural signature: sorted metrics + ordered dims + a
// stable filter key. Used to tell identical_data (DIFFERENT spec, same data) from a
// plain duplicate (same signature — already flagged by the backend).
export function signatureOf(spec: StudioSpec | null | undefined): string {
  const s: any = spec ?? {};
  const metrics = [...((s.metrics as string[]) ?? [])].map(String).sort();
  const dims = [...((s.dimensions as string[]) ?? [])].map(String);
  const filters = ((s.filters as any[]) ?? [])
    .filter((f) => f && typeof f === "object")
    .map((f) => [String(f.field), String(f.op), String(f.value)] as const)
    .sort((a, b) => (a.join("|") < b.join("|") ? -1 : 1));
  return JSON.stringify([metrics, dims, filters]);
}

// A canonical fingerprint of a run RESULT (rows + totals), order-independent, so two
// widgets that render the same numbers are caught even with different specs.
function resultFingerprint(r: RunResult): string {
  const rows = (r.rows ?? [])
    .map((row) => JSON.stringify([row.dims ?? {}, row.metrics ?? {}]))
    .sort();
  return JSON.stringify([rows, r.totals?.metrics ?? {}]);
}

// The distinct values a widget's FIRST breakdown dimension takes across the result
// rows (null/blank folded to one "(belirtilmemiş)" bucket).
function distinctDimValues(spec: StudioSpec, r: RunResult): Set<string> {
  const dim = (spec.dimensions ?? [])[0];
  const out = new Set<string>();
  if (!dim) return out;
  for (const row of r.rows ?? []) {
    const v = row.dims?.[dim];
    out.add(v == null || v === "" ? NL_UNSET : String(v));
  }
  return out;
}

// Detect the data-aware findings from the preview widgets + their fetched results.
// Only widgets with a result are considered (results arrive as previews mount).
export function detectDataFindings(
  widgets: { key: string; title: string | null; spec: StudioSpec }[],
  resultByKey: Record<string, RunResult | undefined>
): Finding[] {
  const findings: Finding[] = [];

  // empty_dimension / single_row (per widget).
  for (const w of widgets) {
    const r = resultByKey[w.key];
    if (!r) continue;
    const dims = w.spec.dimensions ?? [];
    const nRows = (r.rows ?? []).length;
    if (dims.length >= 1) {
      const distinct = distinctDimValues(w.spec, r);
      const onlyUnset = distinct.size === 1 && distinct.has(NL_UNSET);
      if (distinct.size <= 1) {
        findings.push({
          type: "empty_dimension",
          widget_ids: [w.key],
          message: `‘${w.title ?? "Bu widget"}’ kırılımında veri yok${
            onlyUnset ? " (tümü “belirtilmemiş”)" : " (tek değer)"
          }; bu kırılım bir şey katmıyor.`,
        });
      }
    } else if (w.spec.viz !== "kpi" && nRows <= 1) {
      // A breakdown-less table/chart that came back with ≤1 row.
      findings.push({
        type: "single_row",
        widget_ids: [w.key],
        message: `‘${w.title ?? "Bu widget"}’ tek satır döndürdü; tablo/grafik bir şey katmıyor.`,
      });
    }
  }

  // identical_data — DIFFERENT spec, IDENTICAL result. Group by result fingerprint
  // but only pair widgets whose structural signature DIFFERS (same-signature twins
  // are the backend's `duplicate`, not a data-level twin).
  const byPrint = new Map<string, { key: string; title: string | null; sig: string }[]>();
  for (const w of widgets) {
    const r = resultByKey[w.key];
    if (!r || (r.rows ?? []).length === 0) continue; // no empty-vs-empty "twins"
    const print = resultFingerprint(r);
    const arr = byPrint.get(print) ?? [];
    arr.push({ key: w.key, title: w.title, sig: signatureOf(w.spec) });
    byPrint.set(print, arr);
  }
  for (const group of byPrint.values()) {
    const distinctSigs = new Set(group.map((g) => g.sig));
    if (group.length > 1 && distinctSigs.size > 1) {
      const titles = group.map((g) => `‘${g.title ?? "Adsız"}’`).join(" ile ");
      findings.push({
        type: "identical_data",
        widget_ids: group.map((g) => g.key),
        message: `${titles} farklı tanımlı ama aynı veriyi üretiyor.`,
      });
    }
  }

  return findings;
}

// The deterministic option buttons for a finding, labeled from the current draft
// titles. Resolution (trim/retitle) happens client-side via applyOption.
export function optionsFor(f: Finding, titleByKey: Record<string, string | null>): CritiqueOption[] {
  const titleOf = (k: string) => titleByKey[k] ?? "Adsız";
  switch (f.type) {
    case "duplicate":
    case "identical_data":
      return [
        { label: "İkisini de tut", action: { kind: "keep_all" } },
        ...f.widget_ids.map((k) => ({
          label: `Sadece “${titleOf(k)}”`,
          action: { kind: "keep_only" as const, key: k, among: f.widget_ids },
        })),
      ];
    case "empty_dimension":
    case "single_row":
      return [
        { label: "Tut", action: { kind: "keep_all" } },
        { label: "Kaldır", action: { kind: "remove", key: f.widget_ids[0] } },
      ];
    case "mislabel":
      return [
        { label: "Başlığı düzelt", action: { kind: "retitle", key: f.widget_ids[0] } },
        { label: "Olduğu gibi bırak", action: { kind: "keep_all" } },
      ];
  }
}

// Badge shown inline on an affected preview widget.
export function badgeForType(t: FindingType): string {
  switch (t) {
    case "duplicate":
    case "identical_data":
      return "Yinelenen";
    case "empty_dimension":
    case "single_row":
      return "Veri yok";
    case "mislabel":
      return "Etiket uyumsuz";
  }
}

// Apply a chosen option to the draft widget list — PURE (returns a new list). This
// is the ONLY thing that changes the plan, and only on the user's click.
export function applyOption(draft: DraftWidget[], action: OptionAction): DraftWidget[] {
  switch (action.kind) {
    case "keep_all":
      return draft;
    case "remove":
      return draft.filter((d) => d.key !== action.key);
    case "keep_only":
      return draft.filter((d) => d.key === action.key || !action.among.includes(d.key));
    case "retitle":
      return draft.map((d) =>
        d.key === action.key
          ? {
              ...d,
              title: stripPercentLabel(d.title),
              raw: d.raw ? { ...d.raw, title: stripPercentLabel(d.raw.title ?? d.title) } : d.raw,
            }
          : d
      );
  }
}
