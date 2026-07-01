# Yapı UI Style Guide (CR-028)

The data-dense, professional design system (Ramp/Mercury-like). **Refine & adopt,
don't rewrite.** All migrated/new UI composes the `components/ui` primitives + the
tokens via `cn()` — no raw `<button>`, no ad-hoc spacing, no hex colors.

> Proven on the **Ana Sayfa** flagship first. The other 24 pages converge as
> page-per-PR follow-on work using this guide + the checklist below.

---

## 1. Tokens (`src/index.css` + `tailwind.config.js`)

Variable **names are stable**; CR-028 tuned values toward a cooler neutral ramp +
added density/elevation/type tokens. Never hardcode a color — use the class/token.

**Color** — one restrained accent (`brand`), neutrals for everything else,
green/red reserved strictly for financial deltas & status (never decorative):
- Surfaces: `bg-bg` (page), `bg-surface` (card), `hover:bg-surface-hover` (rows/controls)
- Borders: `border-border` (hairline, the primary depth cue), `border-border-strong`
- Text: `text-text-primary`, `text-text-secondary`, `text-text-muted` (overlines), `text-text-disabled`
- Accent: `text-brand` / `bg-brand`. Chrome: `bg-primary` (navy sidebar).
- Status/delta: `text-success` / `text-danger` / `text-warning` + `*-50` tint backgrounds.

**Radius / elevation / density:** `rounded-card` (12px) for cards, `rounded-control`
(8px) for buttons/inputs, `rounded-sm`. `shadow-card` (soft, raised cards),
`shadow-pop` (popovers). `--row-h` (38px) compact table row. Prefer **hairline
borders over shadows** — flat & crisp.

**Type scale (Tailwind `fontSize`):** `text-kpi` (30/700), `text-stat` (22/700),
`text-section` (15/600), `text-caption` (12), `text-overline` (11, uppercase,
tracked). Body is 13–14px. Utilities: `.overline` (muted uppercase label),
`.tabular` (**every number**), `.focus-ring` (keyboard focus).

Fonts: **Inter** (UI) + **JetBrains Mono** (mono), loaded via `index.html`.

---

## 2. Primitives (`components/ui/index.tsx`) — what to use when

| Primitive | Use for |
|---|---|
| `Button` (primary/ghost/danger/outline) | **Every** clickable action. Never a raw `<button>`. |
| `Card` + `CardBody` | Any panel/section surface. |
| `Input` / `Textarea` / `Select` / `Label` / `FieldError` / `Checkbox` | Forms. |
| `Badge` (neutral/info/success/warning/danger) | Tags/statuses. `StatusBadge` composes it for entity statuses. |
| `Stat` | Inline metric (big `.tabular` value + overline label + green/red delta). |
| `KPICard` | The rich dashboard metric **card** (icon + sparkline + click). |
| `SectionTitle` / `Overline` | Section headers & small muted labels. |
| `Toolbar` / `ToolbarSpacer` | Filter/action bars (stop per-page ad-hoc toolbars). |
| `Tabs` | Sectioned pages (accessible, ←/→ keyboard). |
| `PageHeader` (`components/layout/AppLayout`) | Top of **every** page: title + subtitle + action + optional breadcrumb. |
| `Modal` / `SideDrawer` | Centered dialog / right-edge slide-over. Prefer slide-overs for detail views. |
| `DataTable` | All tables. `dense` for ~36px rows; right-align numeric columns (`align:"right"` → auto `.tabular`). Built-in empty/loading/error. |
| `EmptyState` / `LoadError` | Empty vs failed states (never confuse the two). |

---

## 3. Rules

- **Numbers:** always `.tabular`; right-align numeric table columns.
- **Labels:** small muted **uppercase** overlines for field/column/section labels (`.overline` / `Overline`).
- **Density:** use the spacing rhythm + `rounded-card`/`rounded-control`; compact `DataTable dense`.
- **Motion:** ≤150ms transitions on hover/focus/expand; nothing bouncy.
- **A11y:** visible focus (`.focus-ring` or primitive defaults), AA contrast, keyboard-operable.
- **Strings:** Turkish; never reword existing copy during a visual migration.

### ❌ Don't
- ❌ raw `<button>` → use `Button`.
- ❌ inline hex (`#2563eb`, `style={{color:'#...'}}`) → use a token/class.
- ❌ ad-hoc `px-_ py-_ rounded-_ shadow-_` per page → use primitives + tokens.
- ❌ green/red as decoration → reserve for deltas/status.
- ❌ changing data/endpoints/logic/routes/strings during a UI migration.

**Guardrail:** `npm run lint:ui` flags raw `<button>` + inline hex (advisory;
`--strict` to fail). Keep NEW code clean.

---

## 4. Migration checklist (the remaining 24 pages — follow-on, page-per-PR)

For each page: `PageHeader` at top → replace raw `<button>` with `Button` →
`Card`/`SectionTitle` for sections → `DataTable` (dense, right-aligned numbers) →
`Badge`/`StatusBadge` for tags → `Stat`/`KPICard` for metrics → `EmptyState`/
`LoadError`/`Skeleton` states → `.tabular` on figures → `npm run lint:ui` clean →
**verify behavior/strings unchanged + tests green**.

Priority order (per CR-028 §4.1):
1. **Proje Özeti** (`ProjectDashboardPage`)
2. **AIAlertsPage** + **FinansGuvence** (fold CR-022 view into primitives)
3. **AIAssistantPage** (+ fold CR-024 `components/ai/*` trust components in)
4. Cost / budget / hakediş / equipment **list** pages (`BudgetPage`, `InvoicesPage`, `CostFlow`, `EquipmentPage`, …) — lean on `DataTable`
5. **Settings** + remaining forms

Also fold the dashboard's composed widgets (`DashboardToolbar`, `YapiAIRail`,
`DashboardModals`) onto the primitives when their pages are migrated.
