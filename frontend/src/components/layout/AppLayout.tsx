import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import {
  BarChart3,
  Bell,
  Building2,
  Calculator,
  ChevronDown,
  ClipboardCheck,
  FileBarChart,
  FileText,
  FolderKanban,
  HelpCircle,
  History,
  LayoutDashboard,
  LayoutGrid,
  LogOut,
  Menu as MenuIcon,
  MessageSquare,
  PlusSquare,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ScanLine,
  ShieldCheck,
  TrendingUp,
  Users,
  Wrench,
  X,
} from "lucide-react";
import * as React from "react";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { apiGet } from "@/lib/api";
import { useProjectStore } from "@/store/project";
import { NotificationBell } from "@/components/NotificationBell";
import { CommandPalette } from "@/components/CommandPalette";
import { Avatar, Menu, MenuItem, Modal } from "@/components/ui";
import { ROLE_LABELS } from "@/constants";

// CR-029-B §3.2: grouped nav → real YAPI routes (light BuildFlow shell).
const NAV_GROUPS: { group: string; items: { icon: any; label: string; to: string; directorOnly?: boolean }[] }[] = [
  {
    group: "Genel",
    items: [
      { icon: LayoutDashboard, label: "Ana Sayfa", to: "/dashboard" },
      { icon: MessageSquare, label: "Yapı Agent", to: "/ai-assistant" },
      { icon: LayoutGrid, label: "Çalışma Alanım", to: "/workspace" },
    ],
  },
  {
    group: "Portföy",
    items: [
      { icon: FolderKanban, label: "Projeler", to: "/projects" },
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
    group: "Aksiyon",
    items: [
      { icon: ScanLine, label: "Belge Tara", to: "/document-capture" },
      { icon: ClipboardCheck, label: "Onay Bekleyenler", to: "/approvals", directorOnly: true },
      { icon: Bell, label: "Hatırlatıcılar", to: "/reminders" },
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

const PROJECT_NAV = (id: string) => [
  { icon: BarChart3, label: "Proje Özeti", to: `/projects/${id}/dashboard` },
  { icon: Calculator, label: "Bütçe & Maliyetler", to: `/projects/${id}/budget` },
  { icon: FileText, label: "Faturalar & Hakediş", to: `/projects/${id}/invoices` },
  { icon: PlusSquare, label: "Ek İşler", to: `/projects/${id}/variations` },
  { icon: Users, label: "Alt Yükleniciler", to: `/projects/${id}/subcontractors` },
  { icon: TrendingUp, label: "Nakit Akışı", to: `/projects/${id}/cashflow` },
  { icon: Wrench, label: "Ekipman", to: `/projects/${id}/equipment` },
];

// CR-029-B: light nav item — active = blue-soft bg + blue text (mockup .nav-i.on).
function NavItem({ icon: Icon, label, to, active, onNavigate, right }: any) {
  return (
    <Link
      to={to}
      onClick={onNavigate}
      className={cn(
        "flex h-10 items-center gap-2.5 rounded-control px-3 text-[13px] transition-colors",
        active ? "bg-[var(--color-blue-soft)] font-semibold text-brand" : "text-text-secondary hover:bg-surface-hover"
      )}
    >
      <Icon className={cn("h-[18px] w-[18px] shrink-0", active ? "text-brand" : "text-text-muted")} />
      <span className="flex-1 truncate">{label}</span>
      {right}
    </Link>
  );
}

// Shared sidebar body — used by both the desktop sidebar and the mobile drawer.
// `onNavigate` is called whenever a link is tapped so the mobile drawer can close.
function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const isDirector = useAuth((s) => s.user?.role === "director");
  const logoUrl = useAuth((s) => s.user?.company_logo_url);
  const companyName = useAuth((s) => s.user?.company_name);
  const { activeProjectId, activeProjectName, setActiveProject, clearActiveProject } = useProjectStore();
  const [approvalCount, setApprovalCount] = React.useState(0);
  const [projects, setProjects] = React.useState<{ id: string; name: string; status: string }[]>([]);

  // CR-004-H: the active project comes from the URL when on a project page,
  // otherwise from the persisted store — so the submenu survives global pages.
  const effectiveId = params.id ?? activeProjectId ?? undefined;
  const effectiveName = params.id
    ? projects.find((p) => p.id === params.id)?.name ?? activeProjectName ?? "Proje"
    : activeProjectName ?? "Proje";

  React.useEffect(() => {
    if (isDirector) apiGet<any[]>("/approvals").then(({ data }) => setApprovalCount(data?.length ?? 0)).catch(() => setApprovalCount(0));
  }, [isDirector, pathname]);

  React.useEffect(() => {
    apiGet<{ id: string; name: string; status: string }[]>("/projects")
      .then(({ data }) => setProjects(data ?? []))
      .catch(() => setProjects([]));
  }, [params.id]);

  // Remember the project the user is viewing.
  React.useEffect(() => {
    if (params.id) {
      const p = projects.find((x) => x.id === params.id);
      if (p) setActiveProject(p.id, p.name);
    }
  }, [params.id, projects, setActiveProject]);

  // Auto-clear when the active project is deleted or no longer active.
  React.useEffect(() => {
    if (activeProjectId && projects.length && !projects.some((p) => p.id === activeProjectId && p.status === "active")) {
      clearActiveProject();
    }
  }, [projects, activeProjectId, clearActiveProject]);

  const closeContext = () => {
    clearActiveProject();
    navigate("/projects");
    onNavigate?.();
  };

  const GROUP_LABEL = "px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-text-faint";
  return (
    <>
      {/* CR-029-B: logo — gradient cube + Yapı wordmark (or company logo). */}
      <Link to="/dashboard" onClick={onNavigate} className="flex h-12 items-center gap-2.5 px-2 text-text-primary">
        {logoUrl ? (
          <img src={logoUrl} alt={companyName ?? "Şirket"} className="max-h-9 max-w-[150px] object-contain" />
        ) : (
          <>
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-teal text-sm font-bold text-white">Y</span>
            <span className="text-[19px] font-bold">Yapı</span>
          </>
        )}
      </Link>

      <nav className="sidebar-scroll flex-1 space-y-0.5 overflow-y-auto">
        {NAV_GROUPS.map((grp) => (
          <div key={grp.group}>
            <div className={GROUP_LABEL}>{grp.group}</div>
            {grp.items
              .filter((n) => !n.directorOnly || isDirector)
              .map((n) => (
                <NavItem
                  key={n.to}
                  icon={n.icon}
                  label={n.label}
                  to={n.to}
                  active={n.to === "/dashboard" ? pathname === n.to : pathname.startsWith(n.to)}
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

        {/* Active-project context submenu (preserved; light theme). */}
        {effectiveId && (
          <div className="mt-2 border-t border-border pt-2">
            <div className="flex items-center justify-between px-3 pb-1">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-text-faint">Aktif Proje</span>
              <button onClick={closeContext} className="text-text-faint hover:text-text-primary" aria-label="Proje bağlamını kapat">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="truncate px-3 pb-1 text-[13px] font-semibold text-text-primary" title={effectiveName}>{effectiveName}</p>
            {PROJECT_NAV(effectiveId).map((n) => (
              <NavItem key={n.to} {...n} active={pathname === n.to} onNavigate={onNavigate} />
            ))}
            {isDirector && (
              <NavItem
                icon={History}
                label="Denetim İzi"
                to={`/projects/${effectiveId}/audit-log`}
                active={pathname === `/projects/${effectiveId}/audit-log`}
                onNavigate={onNavigate}
              />
            )}
          </div>
        )}
      </nav>

      {/* CR-029-B §3.1: AI Sistem Durumu card + refresh (drives son eşitlenme). */}
      <SystemStatusCard />
    </>
  );
}

// CR-029-B §3.1: "AI Sistem Durumu" — operational dot + last-synced + refresh
// button. Refresh broadcasts a window event the dashboard listens for (re-fetch).
function SystemStatusCard() {
  const [syncedAt, setSyncedAt] = React.useState<number>(() => Date.now());
  const [, force] = React.useReducer((x) => x + 1, 0);
  // Re-render the relative time roughly every minute.
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
    <div className="mt-2 rounded-card border border-border bg-surface p-3 text-caption">
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

// Desktop sidebar (lg and up) — CR-029-B: light BuildFlow shell, 200px.
function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-screen w-[200px] shrink-0 flex-col gap-1 border-r border-border bg-surface-soft p-3.5 lg:flex">
      <SidebarContent />
    </aside>
  );
}

// Mobile slide-in drawer — opened by the hamburger in the top bar.
function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  // Close on Escape and lock body scroll while open.
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
      {/* Backdrop */}
      <div
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-50 bg-black/50 transition-opacity duration-200",
          open ? "opacity-100" : "opacity-0"
        )}
      />
      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85%] flex-col gap-1 bg-surface-soft p-3.5 shadow-xl transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <button
          onClick={onClose}
          aria-label="Menüyü kapat"
          className="absolute right-3 top-4 z-10 text-text-secondary hover:text-text-primary"
        >
          <X className="h-5 w-5" />
        </button>
        <SidebarContent onNavigate={onClose} />
      </div>
    </div>
  );
}

// CR-029-B §4.1: workspace (company) selector in the top-left. Single-company for
// now → the menu offers company settings + new project (project *switching* lives
// in the sidebar/Projeler/⌘K command palette).
function WorkspaceSelector() {
  const navigate = useNavigate();
  const companyName = useAuth((s) => s.user?.company_name);
  return (
    <Menu
      align="left"
      triggerClassName="ctrl-trigger flex h-9 items-center gap-2 rounded-control border border-border bg-surface px-3 text-sm font-semibold text-text-primary transition-colors hover:bg-surface-hover"
      triggerLabel="Çalışma alanı menüsü"
      trigger={
        <>
          <Building2 className="h-4 w-4 text-text-muted" />
          <span className="max-w-[150px] truncate">{companyName ?? "Yapı"}</span>
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

function TopNav({ onMenu }: { onMenu: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
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
  return (
    <header className="flex h-[60px] items-center gap-3 border-b border-border bg-surface px-4 lg:px-4">
      <button onClick={onMenu} className="text-text-secondary hover:text-text-primary lg:hidden" aria-label="Menüyü aç">
        <MenuIcon className="h-5 w-5" />
      </button>
      <WorkspaceSelector />
      <div className="hidden h-[26px] w-px bg-border sm:block" />
      {/* Global search — opens the ⌘K command palette. */}
      <button
        onClick={() => setCmdOpen(true)}
        className="hidden h-9 flex-[0_0_420px] items-center gap-2 rounded-control border border-border bg-surface px-3 text-sm text-text-faint transition-colors hover:bg-surface-hover md:flex"
      >
        <Search className="h-4 w-4 text-text-muted" />
        <span>Proje, belge, fatura, rapor ara…</span>
        <span className="ml-auto rounded-[5px] border border-border px-1.5 py-px text-[11px] text-text-muted">⌘K</span>
      </button>
      <div className="flex-1" />
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
          <p><span className="font-semibold">Yapı'ya sor:</span> üstteki AI komut çubuğuna doğal dille soru sorun; yanıt kaynaklarıyla birlikte açılır.</p>
          <p><span className="font-semibold">⌘K / Ctrl+K:</span> hızlı arama ve komut menüsünü açar.</p>
          <p className="text-text-secondary">Daha fazla yardım için yöneticinizle veya destek ekibiyle iletişime geçin.</p>
        </div>
      </Modal>
    </header>
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

export function AppLayout() {
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const { pathname } = useLocation();

  // Close the mobile drawer on route change (covers links that don't pass onNavigate).
  React.useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // CR-029-B (hybrid): the dashboard command center is full-bleed (it owns its
  // grid + padding); every other page keeps the centered, padded container.
  const isDashboard = pathname === "/dashboard";

  return (
    <div className="flex h-full">
      <Sidebar />
      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopNav onMenu={() => setDrawerOpen(true)} />
        <main className="flex-1 overflow-y-auto pb-20 lg:pb-0">
          {isDashboard ? (
            <Outlet />
          ) : (
            <div className="mx-auto max-w-[calc(50%_+_700px)] p-4 lg:p-6">
              <Outlet />
            </div>
          )}
        </main>
      </div>
      <MobileNav />
    </div>
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
