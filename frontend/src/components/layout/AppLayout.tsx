import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import {
  Banknote,
  Bell,
  BarChart3,
  Building2,
  CalendarRange,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  FileBarChart,
  FolderKanban,
  HelpCircle,
  History,
  Layers,
  LayoutDashboard,
  LayoutGrid,
  LogOut,
  Menu as MenuIcon,
  MessageSquare,
  Plus,
  RefreshCw,
  Rss,
  Search,
  Settings,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Users,
  X,
  Zap,
} from "lucide-react";
import * as React from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { cachedGet } from "@/lib/requestCache";
import { NotificationBell } from "@/components/NotificationBell";
import { CommandPalette } from "@/components/CommandPalette";
import { CurrencyToggle } from "@/components/currency";
import { SideDrawer } from "@/components/SideDrawer";
import { Avatar, Menu, MenuItem, Modal } from "@/components/ui";
import { ROLE_LABELS } from "@/constants";
import { RANGE_LABELS, useDashboardFilters } from "@/store/dashboardFilters";
import { useLayoutPrefs } from "@/store/layoutPrefs";
import { ShellSlotsProvider, useShellSlots } from "./ShellSlots";
import { SectionNav, type NavEntry, type SectionDef } from "./SectionNav";
import { NavItemRow } from "./NavItemRow";
import { ProjectRail } from "./ProjectRail";
import { StudioRail } from "./StudioRail";

// CR-029-B §3.2 + CR-038: grouped nav → real YAPI routes. CR-038 promotes
// "Yapı AI" to a top-level hero link (out of Genel) and drops the duplicate
// "Yapı AI" coming-soon item from Stüdyo. The groups remain the single source of
// truth — the top-bar SectionNav and the mobile drawer both reshape this list.
const NAV_GROUPS: { group: string; items: NavEntry[] }[] = [
  {
    group: "Genel",
    items: [
      { icon: LayoutDashboard, label: "Ana Sayfa", to: "/dashboard" },
      { icon: LayoutGrid, label: "Çalışma Alanım", to: "/workspace" },
    ],
  },
  {
    group: "Portföy",
    items: [
      { icon: FolderKanban, label: "Projeler", to: "/projects" },
      { icon: Layers, label: "Portföy", to: "#portfolio", comingSoon: true },
      { icon: Banknote, label: "Nakit Akışı", to: "#cashflow", comingSoon: true },
      { icon: Building2, label: "Tedarikçiler", to: "/vendors" },
    ],
  },
  {
    group: "Finans",
    items: [
      { icon: FileBarChart, label: "Raporlar", to: "/reports" },
      { icon: ShieldCheck, label: "Finans Güvence & Uyarılar", to: "/ai-alerts" },
    ],
  },
  {
    group: "Stüdyo",
    items: [
      { icon: BarChart3, label: "Rapor Stüdyosu", to: "/studio/reports" },
      { icon: LayoutDashboard, label: "Panolar", to: "/studio/dashboards" },
      { icon: Users, label: "Segmentler", to: "#segments", comingSoon: true },
    ],
  },
  {
    group: "Aksiyon",
    items: [
      { icon: ScanLine, label: "Belge Tara", to: "/document-capture" },
      { icon: ClipboardCheck, label: "Onay Bekleyenler", to: "/approvals", directorOnly: true },
      { icon: Bell, label: "Hatırlatıcılar", to: "/reminders" },
    ],
  },
  {
    group: "AI & Ekip",
    items: [
      { icon: Sparkles, label: "Uygulamalar", to: "/studio/skills" },
      { icon: Zap, label: "Otomasyonlar", to: "/automations" },
      { icon: Rss, label: "Ekip Akışı", to: "#feed", comingSoon: true },
      { icon: Users, label: "Ekip", to: "#team", comingSoon: true },
    ],
  },
  {
    group: "Yönetim",
    items: [
      { icon: Settings, label: "Ayarlar", to: "/settings" },
      { icon: History, label: "Denetim İzi", to: "/audit-log", directorOnly: true },
    ],
  },
];

// CR-038 (founder order): Genel · Yapı AI · Stüdyo · Portföy · Finans · Aksiyon ·
// AI & Ekip · Yönetim. "Yapı AI" is a direct hero link; the rest are dropdowns.
// "Çalışma Alanım" stays reachable inside the small "Genel" group.
const SECTIONS: SectionDef[] = (() => {
  const byGroup: Record<string, NavEntry[]> = {};
  NAV_GROUPS.forEach((g) => (byGroup[g.group] = g.items));
  const menu = (key: string, label: string): SectionDef => ({ kind: "menu", key, label, items: byGroup[label] ?? [] });
  return [
    menu("genel", "Genel"),
    { kind: "link", key: "yapi-ai", label: "Yapı AI", to: "/ai-assistant", icon: Sparkles, hero: true },
    menu("studio", "Stüdyo"),
    menu("portfoy", "Portföy"),
    menu("finans", "Finans"),
    menu("aksiyon", "Aksiyon"),
    menu("ai-ekip", "AI & Ekip"),
    menu("yonetim", "Yönetim"),
  ];
})();

const GROUP_LABEL = "px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-text-faint";

type RailKind = "ai" | "project" | "studio" | null;
function matchRailRoute(pathname: string): RailKind {
  if (pathname.startsWith("/ai-assistant")) return "ai";
  if (/^\/projects\/[^/]+\/.+/.test(pathname)) return "project";
  if (pathname.startsWith("/studio")) return "studio";
  return null;
}

// CR-029-B: company logo / Yapı wordmark — preserved (white-label aware).
function BrandLogo({ onNavigate }: { onNavigate?: () => void }) {
  const logoUrl = useAuth((s) => s.user?.company_logo_url);
  const companyName = useAuth((s) => s.user?.company_name);
  return (
    <Link to="/dashboard" onClick={onNavigate} className="focus-ring flex h-9 items-center gap-2 rounded-control px-1 text-text-primary">
      {logoUrl ? (
        <img src={logoUrl} alt={companyName ?? "Şirket"} className="max-h-8 max-w-[140px] object-contain" />
      ) : (
        <>
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-teal text-sm font-bold text-white">
            Y
          </span>
          <span className="hidden text-[18px] font-bold sm:inline">Yapı</span>
        </>
      )}
    </Link>
  );
}

// CR-029-B §3.1: "AI Sistem Durumu" — operational dot + last-synced + refresh.
function SystemStatusCard() {
  const [syncedAt, setSyncedAt] = React.useState<number>(() => Date.now());
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    const t = window.setInterval(force, 60_000);
    return () => window.clearInterval(t);
  }, []);
  const refresh = () => {
    window.dispatchEvent(new CustomEvent("yapi:refresh"));
    setSyncedAt(Date.now());
  };
  const mins = Math.max(0, Math.round((Date.now() - syncedAt) / 60_000));
  const rel = mins === 0 ? "az önce" : `${mins} dk önce`;
  return (
    <div className="rounded-card border border-border bg-surface p-3 text-caption">
      <div className="mb-1.5 font-semibold text-text-primary">AI Sistem Durumu</div>
      <div className="flex items-center gap-2 text-text-secondary">
        <span className="h-2 w-2 rounded-full bg-success" /> Tüm sistemler çalışıyor
      </div>
      <div className="mt-2 flex items-end justify-between border-t border-border pt-2">
        <div className="text-text-faint">
          <div>Veriler en son eşitlendi</div>
          <div className="font-medium text-text-secondary">{rel}</div>
        </div>
        <button
          onClick={refresh}
          title="Verileri yenile ve yeniden eşitle"
          aria-label="Verileri yenile"
          className="focus-ring flex h-[26px] w-[26px] items-center justify-center rounded-sm border border-border bg-surface text-text-secondary transition-colors hover:bg-surface-hover"
        >
          <RefreshCw className="h-[15px] w-[15px]" />
        </button>
      </div>
    </div>
  );
}

// Shared role/approval-count helper for the nav surfaces.
function useApprovalCount() {
  const isDirector = useAuth((s) => s.user?.role === "director");
  const { pathname } = useLocation();
  const [approvalCount, setApprovalCount] = React.useState(0);
  React.useEffect(() => {
    if (isDirector)
      cachedGet<any[]>("/approvals")
        .then(({ data }) => setApprovalCount(data?.length ?? 0))
        .catch(() => setApprovalCount(0));
  }, [isDirector, pathname]);
  return { isDirector, approvalCount };
}

// CR-038: grouped nav for the mobile drawer (the lg→ hamburger target). Mirrors
// the old sidebar: Yapı AI + the groups + the active-project submenu.
function MobileNavContent({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const { isDirector, approvalCount } = useApprovalCount();
  const isItemActive = (to: string) => (to === "/dashboard" ? pathname === to : pathname.startsWith(to));
  return (
    <nav className="sidebar-scroll flex-1 space-y-0.5 overflow-y-auto">
      <NavItemRow icon={Sparkles} label="Yapı AI" to="/ai-assistant" active={isItemActive("/ai-assistant")} onNavigate={onNavigate} />
      {NAV_GROUPS.map((grp) => (
        <div key={grp.group}>
          <div className={GROUP_LABEL}>{grp.group}</div>
          {grp.items
            .filter((n) => !n.directorOnly || isDirector)
            .map((n) => (
              <NavItemRow
                key={n.to}
                icon={n.icon}
                label={n.label}
                to={n.to}
                comingSoon={n.comingSoon}
                active={n.comingSoon ? false : isItemActive(n.to)}
                onNavigate={onNavigate}
                right={
                  n.to === "/approvals" && approvalCount > 0 ? (
                    <span className="rounded-full bg-danger px-1.5 text-[10px] font-bold leading-[16px] text-white">{approvalCount}</span>
                  ) : undefined
                }
              />
            ))}
        </div>
      ))}
      <div className="mt-2 border-t border-border pt-2">
        <ProjectRail onNavigate={onNavigate} />
      </div>
    </nav>
  );
}

// Mobile slide-in drawer — opened by the hamburger in the top bar.
function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  return (
    <div className={cn("lg:hidden", open ? "" : "pointer-events-none")} aria-hidden={!open}>
      <div
        onClick={onClose}
        className={cn("fixed inset-0 z-50 bg-black/50 transition-opacity duration-200", open ? "opacity-100" : "opacity-0")}
      />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85%] flex-col gap-1 bg-surface-soft p-3.5 shadow-xl transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <button onClick={onClose} aria-label="Menüyü kapat" className="absolute right-3 top-4 z-10 text-text-secondary hover:text-text-primary">
          <X className="h-5 w-5" />
        </button>
        <BrandLogo onNavigate={onClose} />
        <MobileNavContent onNavigate={onClose} />
        <SystemStatusCard />
      </div>
    </div>
  );
}

// CR-029-B §4.1: workspace (company) selector in the top-left.
function WorkspaceSelector() {
  const navigate = useNavigate();
  const companyName = useAuth((s) => s.user?.company_name);
  return (
    <Menu
      align="left"
      triggerClassName="ctrl-trigger hidden h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-sm font-semibold text-text-primary transition-colors hover:bg-surface-hover sm:flex"
      triggerLabel="Çalışma alanı menüsü"
      trigger={
        <>
          <Building2 className="h-4 w-4 text-text-muted" />
          <span className="max-w-[140px] truncate">{companyName ?? "Yapı"}</span>
          <ChevronDown className="h-4 w-4 text-text-muted" />
        </>
      }
    >
      {(close) => (
        <>
          <MenuItem icon={Settings} onClick={() => { close(); navigate("/settings"); }}>Şirket Ayarları</MenuItem>
          <MenuItem icon={Plus} onClick={() => { close(); navigate("/projects/new"); }}>Yeni Proje</MenuItem>
        </>
      )}
    </Menu>
  );
}

// CR-029 fix #1: dashboard-scoped header controls — date range, project filter, currency.
function DashboardHeaderControls() {
  const navigate = useNavigate();
  const { range, setRange } = useDashboardFilters();
  const [projects, setProjects] = React.useState<{ id: string; name: string }[]>([]);
  React.useEffect(() => {
    cachedGet<{ id: string; name: string; status: string }[]>("/projects")
      .then(({ data }) => setProjects((data ?? []).filter((p) => p.status === "active").map((p) => ({ id: p.id, name: p.name }))))
      .catch(() => setProjects([]));
  }, []);
  const ctrl = "ctrl flex h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-[13px] text-text-secondary transition-colors hover:bg-surface-hover";
  return (
    <>
      <Menu
        align="right"
        triggerLabel="Tarih aralığı"
        triggerClassName={cn(ctrl, "hidden md:flex")}
        trigger={<><CalendarRange className="h-4 w-4 text-text-muted" /><span>{RANGE_LABELS[range]}</span><ChevronDown className="h-4 w-4 text-text-muted" /></>}
      >
        {(close) => (
          <>
            {(Object.keys(RANGE_LABELS) as (keyof typeof RANGE_LABELS)[]).map((k) => (
              <MenuItem key={k} onClick={() => { setRange(k); close(); }}>
                <span className={range === k ? "font-semibold text-brand" : ""}>{RANGE_LABELS[k]}</span>
              </MenuItem>
            ))}
          </>
        )}
      </Menu>
      <Menu
        align="right"
        triggerLabel="Proje filtresi"
        triggerClassName={cn(ctrl, "hidden xl:flex")}
        width={240}
        trigger={<><FolderKanban className="h-4 w-4 text-text-muted" /><span>Tüm Projeler</span><ChevronDown className="h-4 w-4 text-text-muted" /></>}
      >
        {(close) => (
          <>
            <MenuItem onClick={() => { close(); navigate("/dashboard"); }}><span className="font-semibold text-brand">Tüm Projeler</span></MenuItem>
            {projects.length === 0 && <div className="px-3 py-1.5 text-[11px] text-text-muted">Aktif proje yok</div>}
            {projects.map((p) => (
              <MenuItem key={p.id} onClick={() => { close(); navigate(`/projects/${p.id}/dashboard`); }}>{p.name}</MenuItem>
            ))}
          </>
        )}
      </Menu>
      <div className="hidden xl:block"><CurrencyToggle /></div>
    </>
  );
}

function TopNav({ onMenu }: { onMenu: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const isDashboard = pathname === "/dashboard";
  const { isDirector, approvalCount } = useApprovalCount();
  const [cmdOpen, setCmdOpen] = React.useState(false);
  const [helpOpen, setHelpOpen] = React.useState(false);
  const roleLabel = user?.role ? ROLE_LABELS[user.role] ?? user.role : null;

  // ⌘K opens the global command palette (the dashboard's AI command bar
  // intercepts ⌘K with a capture-phase listener while it is mounted).
  React.useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen(true);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const isItemActive = (to: string) => (to === "/dashboard" ? pathname === to : pathname.startsWith(to));
  const isSectionActive = (s: SectionDef) =>
    s.kind === "link" ? pathname.startsWith(s.to) : s.items.some((it) => !it.comingSoon && isItemActive(it.to));

  return (
    <header className="flex h-[60px] shrink-0 items-center gap-2 border-b border-border bg-surface px-4">
      <button onClick={onMenu} className="text-text-secondary hover:text-text-primary lg:hidden" aria-label="Menüyü aç">
        <MenuIcon className="h-5 w-5" />
      </button>
      <BrandLogo />
      <div className="hidden h-[26px] w-px bg-border lg:block" />
      <WorkspaceSelector />
      <div className="hidden h-[26px] w-px bg-border lg:block" />
      <SectionNav
        sections={SECTIONS}
        isDirector={isDirector}
        approvalCount={approvalCount}
        isSectionActive={isSectionActive}
        isItemActive={isItemActive}
      />
      <div className="flex-1 lg:hidden" />
      <button
        onClick={() => setCmdOpen(true)}
        className="hidden h-9 w-[260px] items-center gap-2 rounded-control border border-border bg-surface px-3 text-sm text-text-faint transition-colors hover:bg-surface-hover xl:flex"
      >
        <Search className="h-4 w-4 text-text-muted" />
        <span className="truncate">Ara…</span>
        <span className="ml-auto rounded-[5px] border border-border px-1.5 py-px text-[11px] text-text-muted">⌘K</span>
      </button>
      {isDashboard && <DashboardHeaderControls />}
      <NotificationBell />
      <Menu
        triggerLabel="Kullanıcı menüsü"
        triggerClassName="flex items-center gap-2"
        trigger={
          <>
            <Avatar name={user?.full_name} size={34} />
            <span className="hidden flex-col items-start leading-tight sm:flex">
              <span className="text-[13px] font-semibold text-text-primary">{user?.full_name}</span>
              {roleLabel && <span className="text-[10px] text-text-muted">{roleLabel}</span>}
            </span>
            <ChevronDown className="h-[15px] w-[15px] text-text-faint" />
          </>
        }
      >
        {(close) => (
          <>
            <div className="border-b border-border px-3 py-2 text-xs text-text-secondary">{user?.email}</div>
            <MenuItem icon={Settings} onClick={() => { close(); navigate("/settings"); }}>Profil &amp; Ayarlar</MenuItem>
            <MenuItem icon={HelpCircle} onClick={() => { close(); setHelpOpen(true); }}>Yardım</MenuItem>
            <MenuItem icon={LogOut} danger onClick={async () => { close(); await logout(); navigate("/login"); }}>Çıkış Yap</MenuItem>
          </>
        )}
      </Menu>
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
      <Modal open={helpOpen} title="Yapı — Hızlı Yardım" onClose={() => setHelpOpen(false)} size="md">
        <div className="space-y-3 text-sm text-text-primary">
          <p><span className="font-semibold">Ana Sayfa:</span> tüm aktif projelerinizin finansal komuta merkezi — AI brifingi, KPI'lar, grafikler, proje risk tablosu ve aksiyon kuyruğu.</p>
          <p><span className="font-semibold">Yapı AI:</span> üst menüden Yapı AI'ya gidin; araçlarla analiz yapan yapay zeka ajanına doğal dille soru sorun, yanıt kaynaklarıyla birlikte açılır.</p>
          <p><span className="font-semibold">⌘K / Ctrl+K:</span> hızlı arama ve komut menüsünü açar.</p>
          <p className="text-text-secondary">Daha fazla yardım için yöneticinizle veya destek ekibiyle iletişime geçin.</p>
        </div>
      </Modal>
    </header>
  );
}

// Rail collapse toggle (desktop).
function RailHeader({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <div className={cn("flex h-10 shrink-0 items-center px-3", collapsed ? "justify-center" : "justify-end")}>
      <button
        onClick={onToggle}
        aria-label={collapsed ? "Kenar çubuğunu genişlet" : "Kenar çubuğunu daralt"}
        aria-expanded={!collapsed}
        title={collapsed ? "Genişlet" : "Daralt"}
        className="focus-ring flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
      >
        {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </button>
    </div>
  );
}

function MobileNav() {
  const { pathname } = useLocation();
  const items = [
    { icon: LayoutDashboard, label: "Ana Sayfa", to: "/dashboard" },
    { icon: FolderKanban, label: "Projeler", to: "/projects" },
    { icon: ScanLine, label: "Belge Tara", to: "/document-capture" },
    { icon: Bell, label: "Hatırlatıcı", to: "/reminders" },
    { icon: Settings, label: "Profil", to: "/settings" },
  ];
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 flex border-t border-border bg-surface lg:hidden">
      {items.map((n) => (
        <Link
          key={n.label}
          to={n.to}
          className={cn(
            "flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px]",
            pathname === n.to ? "text-primary" : "text-text-secondary"
          )}
        >
          <n.icon className="h-5 w-5" />
          {n.label}
        </Link>
      ))}
    </nav>
  );
}

// CR-038 §7-C: the 3-zone shell. Top bar (full width) over [left rail | main |
// right panel]. The left-rail content is route-driven: agent slot on
// /ai-assistant, the store-backed project/studio rails on their routes, else
// nothing (main goes full width). The right panel is the agent page's slot.
function AppShell() {
  const { pathname } = useLocation();
  const { leftRail, rightPanel } = useShellSlots();
  const { railCollapsed, toggleRail } = useLayoutPrefs();
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [railSheetOpen, setRailSheetOpen] = React.useState(false);

  React.useEffect(() => {
    setDrawerOpen(false);
    setRailSheetOpen(false);
  }, [pathname]);

  const railKind = matchRailRoute(pathname);
  // CR-029-B (hybrid) + CR-038: the dashboard and the Yapı AI page are full-bleed
  // (they own their grid/padding); every other page keeps the centered container.
  const fullBleed = pathname === "/dashboard" || pathname.startsWith("/ai-assistant");

  const railContent =
    railKind === "ai" ? leftRail : railKind === "project" ? <ProjectRail /> : railKind === "studio" ? <StudioRail /> : null;

  return (
    <div className="flex h-full flex-col">
      <TopNav onMenu={() => setDrawerOpen(true)} />
      <div className="flex min-h-0 flex-1">
        {railKind !== null && (
          <aside
            className={cn(
              "relative hidden shrink-0 flex-col border-r border-border bg-surface-soft transition-[width] duration-200 ease-out lg:flex",
              railCollapsed ? "w-[52px]" : "w-[248px]"
            )}
          >
            <RailHeader collapsed={railCollapsed} onToggle={toggleRail} />
            {!railCollapsed && (
              <>
                <div className="sidebar-scroll flex-1 overflow-y-auto px-3 pb-3">{railContent}</div>
                <div className="border-t border-border p-3">
                  <SystemStatusCard />
                </div>
              </>
            )}
          </aside>
        )}

        <main className="min-w-0 flex-1 overflow-y-auto pb-20 lg:pb-0">
          {fullBleed ? (
            <Outlet />
          ) : (
            <div className="mx-auto max-w-[calc(50%_+_700px)] p-4 lg:p-6">
              <Outlet />
            </div>
          )}
        </main>

        {railKind === "ai" && rightPanel && (
          <aside className="hidden w-[340px] shrink-0 overflow-y-auto border-l border-border bg-surface-soft xl:block">
            {rightPanel}
          </aside>
        )}
      </div>

      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      {/* Mobile agent-rail sheet (§I): reach sessions / new chat / agents below lg. */}
      {railKind === "ai" && (
        <>
          <button
            onClick={() => setRailSheetOpen(true)}
            className="focus-ring fixed bottom-20 left-4 z-30 flex items-center gap-1.5 rounded-full border border-border bg-surface px-3.5 py-2.5 text-sm font-medium text-brand shadow-lg lg:hidden"
            aria-label="Sohbetler"
          >
            <MessageSquare className="h-4 w-4" /> Sohbetler
          </button>
          <div className="lg:hidden">
            <SideDrawer open={railSheetOpen} title="Sohbetler" onClose={() => setRailSheetOpen(false)}>
              {leftRail}
            </SideDrawer>
          </div>
        </>
      )}

      <MobileNav />
    </div>
  );
}

export function AppLayout() {
  return (
    <ShellSlotsProvider>
      <AppShell />
    </ShellSlotsProvider>
  );
}

// Page header helper
export function PageHeader({
  title,
  subtitle,
  action,
  breadcrumb,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  /** CR-028: optional overline breadcrumb/eyebrow above the title. */
  breadcrumb?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div className="min-w-0">
        {breadcrumb && <div className="overline mb-1">{breadcrumb}</div>}
        <h1 className="text-2xl font-bold text-primary">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-text-secondary">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
