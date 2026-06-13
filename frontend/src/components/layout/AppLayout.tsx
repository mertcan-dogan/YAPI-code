import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import {
  BarChart3,
  Bell,
  Calculator,
  ChevronDown,
  ClipboardCheck,
  FileBarChart,
  FileText,
  FolderKanban,
  HelpCircle,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  PlusSquare,
  Plus,
  Send,
  Settings,
  ScanLine,
  Sparkles,
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
import { Modal } from "@/components/ui";
import { ROLE_LABELS } from "@/constants";

const GLOBAL_NAV = [
  { icon: LayoutDashboard, label: "Ana Sayfa", to: "/dashboard" },
  { icon: FolderKanban, label: "Projeler", to: "/projects" },
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

const BOTTOM_NAV = [
  { icon: Bell, label: "Hatırlatıcılar", to: "/reminders" },
  { icon: FileBarChart, label: "Raporlar", to: "/reports" },
  { icon: Sparkles, label: "Yapay Zeka Uyarıları", to: "/ai-alerts" },
  { icon: MessageSquare, label: "AI Asistan", to: "/ai-assistant" },
  { icon: ScanLine, label: "Belge Tara", to: "/document-capture" },
  { icon: Settings, label: "Ayarlar", to: "/settings" },
];

function NavItem({ icon: Icon, label, to, active, onNavigate }: any) {
  return (
    <Link
      to={to}
      onClick={onNavigate}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        active
          ? "bg-white/10 text-white shadow-[inset_2px_0_0_var(--color-brand-2)]"
          : "text-white/60 hover:bg-white/5 hover:text-white"
      )}
    >
      <Icon className={cn("h-4 w-4 shrink-0", active && "text-brand-2")} />
      <span className="truncate">{label}</span>
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
  const [aiQuery, setAiQuery] = React.useState("");

  const askYapiAI = () => {
    const q = aiQuery.trim();
    if (!q) return;
    setAiQuery("");
    onNavigate?.();
    navigate("/ai-assistant", { state: { q } });
  };

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

  return (
    <>
      <Link to="/dashboard" onClick={onNavigate} className="flex items-center gap-2 px-5 py-4 text-white">
        {logoUrl ? (
          <img src={logoUrl} alt={companyName ?? "Şirket"} className="max-h-10 max-w-[180px] object-contain" />
        ) : (
          <>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-brand-2 font-bold text-white">Y</div>
            <span className="text-lg font-bold">{companyName ?? "Yapı"}</span>
          </>
        )}
      </Link>
      <nav className="sidebar-scroll flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {GLOBAL_NAV.map((n) => (
          <NavItem key={n.to} {...n} active={pathname === n.to} onNavigate={onNavigate} />
        ))}
        {effectiveId && (
          <div className="mt-3 border-t border-white/10 pt-3">
            <div className="flex items-center justify-between px-3 pb-1">
              <span className="text-[10px] uppercase tracking-wide text-white/40">Aktif Proje</span>
              <button onClick={closeContext} className="text-white/40 hover:text-white" aria-label="Proje bağlamını kapat">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="truncate px-3 pb-2 text-[13px] font-bold text-white" title={effectiveName}>{effectiveName}</p>
            {PROJECT_NAV(effectiveId).map((n) => (
              <NavItem key={n.to} {...n} active={pathname === n.to} onNavigate={onNavigate} />
            ))}
            {/* CR-001-H: Denetim İzi — director only, under Ekipman */}
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
        <div className="mt-3 border-t border-white/10 pt-3">
          {BOTTOM_NAV.map((n) => (
            <NavItem key={n.to} {...n} active={pathname.startsWith(n.to)} onNavigate={onNavigate} />
          ))}
          {isDirector && (
            <Link
              to="/approvals"
              onClick={onNavigate}
              className={cn(
                "flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                pathname === "/approvals" ? "bg-primary-light text-white" : "text-white/70 hover:bg-primary-light/60 hover:text-white"
              )}
            >
              <span className="flex items-center gap-3"><ClipboardCheck className="h-4 w-4 shrink-0" /> Onay Bekleyenler</span>
              {approvalCount > 0 && <span className="rounded-full bg-danger px-1.5 text-[10px] font-bold text-white">{approvalCount}</span>}
            </Link>
          )}
          {isDirector && (
            <NavItem icon={History} label="Denetim İzi" to="/audit-log" active={pathname === "/audit-log"} onNavigate={onNavigate} />
          )}
        </div>
      </nav>
      {/* Yapı AI agent box — inline question that hands off to the AI assistant. */}
      <div className="border-t border-white/10 px-3 py-3">
        <div className="rounded-xl bg-white/5 p-3">
          <div className="mb-2 flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-brand to-brand-2 text-white">
              <Sparkles className="h-3.5 w-3.5" />
            </span>
            <span className="text-[13px] font-semibold text-white">Yapı AI</span>
            <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-brand-2">Beta</span>
          </div>
          <div className="flex items-center gap-1.5 rounded-lg bg-primary px-2 ring-1 ring-white/10 focus-within:ring-brand-2">
            <input
              value={aiQuery}
              onChange={(e) => setAiQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && askYapiAI()}
              placeholder="Bir şey sor…"
              className="min-w-0 flex-1 bg-transparent py-2 text-[13px] text-white placeholder:text-white/40 outline-none"
            />
            <button onClick={askYapiAI} disabled={!aiQuery.trim()} className="text-brand-2 disabled:text-white/30" aria-label="Yapı AI'ya sor">
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
      {/* Brand footer — small persistent Yapı mark, shows even when a company logo is set */}
      <div className="flex items-center justify-center gap-1.5 border-t border-white/10 px-5 py-3">
        <span className="flex h-4 w-4 items-center justify-center rounded-sm bg-gradient-to-br from-brand to-brand-2 text-[10px] font-bold leading-none text-white">Y</span>
        <span className="text-[11px] font-medium tracking-wide text-white/40">Powered by Yapı</span>
      </div>
    </>
  );
}

// Desktop sidebar (lg and up).
function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col bg-primary lg:flex">
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
          "fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85%] flex-col bg-primary shadow-xl transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <button
          onClick={onClose}
          aria-label="Menüyü kapat"
          className="absolute right-3 top-4 z-10 text-white/60 hover:text-white"
        >
          <X className="h-5 w-5" />
        </button>
        <SidebarContent onNavigate={onClose} />
      </div>
    </div>
  );
}

// CR-002-G: clickable project selector in the top-left.
function ProjectSelector() {
  const navigate = useNavigate();
  const params = useParams();
  const { activeProjectId, setActiveProject } = useProjectStore();
  const [open, setOpen] = React.useState(false);
  const [projects, setProjects] = React.useState<{ id: string; name: string }[]>([]);

  React.useEffect(() => {
    apiGet<{ id: string; name: string; status: string }[]>("/projects")
      .then(({ data }) => setProjects((data ?? []).filter((p) => p.status === "active")))
      .catch(() => setProjects([]));
  }, []);

  const selectedId = params.id ?? activeProjectId;
  const current = projects.find((p) => p.id === selectedId);
  const choose = (p: { id: string; name: string }) => {
    setActiveProject(p.id, p.name);
    setOpen(false);
    navigate(`/projects/${p.id}/dashboard`);
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 text-sm text-text-primary hover:bg-bg sm:px-3"
      >
        <FolderKanban className="h-4 w-4 text-brand" />
        <span className="max-w-[120px] truncate sm:max-w-[200px]">{current?.name ?? "Proje Seç"}</span>
        <ChevronDown className="h-4 w-4 text-text-secondary" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-11 z-20 max-h-80 w-64 overflow-auto rounded-md border border-border bg-surface py-1 shadow-lg">
            {projects.length === 0 && <div className="px-3 py-2 text-xs text-text-secondary">Aktif proje yok</div>}
            {projects.map((p) => (
              <button
                key={p.id}
                onClick={() => choose(p)}
                className={cn("flex w-full items-center px-3 py-2 text-left text-sm hover:bg-navy-50", p.id === selectedId && "font-semibold text-primary")}
              >
                <span className="truncate">{p.name}</span>
              </button>
            ))}
            <div className="mt-1 border-t border-border">
              <button
                onClick={() => { setOpen(false); navigate("/projects/new"); }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-primary-light hover:bg-navy-50"
              >
                <Plus className="h-4 w-4" /> Yeni Proje
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function TopNav({ onMenu }: { onMenu: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const [cmdOpen, setCmdOpen] = React.useState(false);
  const [helpOpen, setHelpOpen] = React.useState(false);
  const roleLabel = user?.role ? ROLE_LABELS[user.role] ?? user.role : null;
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
    <header className="flex h-16 items-center justify-between border-b border-border bg-surface px-4 lg:px-6">
      <div className="flex items-center gap-3">
        <button onClick={onMenu} className="text-text-secondary hover:text-primary lg:hidden" aria-label="Menüyü aç">
          <Menu className="h-5 w-5" />
        </button>
        <ProjectSelector />
        <button
          onClick={() => setCmdOpen(true)}
          className="hidden items-center gap-2 rounded-xl border border-border bg-bg px-3 py-2 text-sm text-text-secondary transition-colors hover:border-brand md:flex"
        >
          <Sparkles className="h-4 w-4 text-brand" />
          <span>Ara, sor veya komut ver…</span>
          <span className="ml-2 rounded border border-border bg-surface px-1.5 py-0.5 text-[10px] text-text-disabled">⌘K</span>
        </button>
      </div>
      <div className="relative flex items-center gap-3">
        <button
          onClick={() => setHelpOpen(true)}
          className="text-text-secondary transition-colors hover:text-primary"
          aria-label="Yardım"
          title="Yardım"
        >
          <HelpCircle className="h-5 w-5" />
        </button>
        <NotificationBell />
        <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-2 text-sm font-medium text-white">
            {user?.full_name?.charAt(0) ?? "K"}
          </div>
          <span className="hidden flex-col items-start leading-tight sm:flex">
            <span className="text-sm text-text-primary">{user?.full_name}</span>
            {roleLabel && <span className="text-[11px] text-text-secondary">{roleLabel}</span>}
          </span>
        </button>
        {open && (
          <div className="absolute right-0 top-12 w-48 rounded-md border border-border bg-surface py-1 shadow-lg">
            <div className="border-b border-border px-3 py-2 text-xs text-text-secondary">{user?.email}</div>
            <Link to="/settings" onClick={() => setOpen(false)} className="flex w-full items-center gap-2 px-3 py-2 text-sm text-text-primary hover:bg-bg">
              <Settings className="h-4 w-4" /> Ayarlar
            </Link>
            <button
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-danger hover:bg-bg"
            >
              <LogOut className="h-4 w-4" /> Çıkış Yap
            </button>
          </div>
        )}
      </div>
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
      <Modal open={helpOpen} title="Yapı — Hızlı Yardım" onClose={() => setHelpOpen(false)} size="md">
        <div className="space-y-3 text-sm text-text-primary">
          <p><span className="font-semibold">Ana Sayfa:</span> tüm aktif projelerinizin finansal portföy görünümü — KPI'lar, performans grafiği, bütçe dağılımı ve gelen belgeler.</p>
          <p><span className="font-semibold">Filtreler &amp; Tarih:</span> üstteki tarih aralığı ve Filtreler ile panoyu daraltabilirsiniz.</p>
          <p><span className="font-semibold">Yapı AI:</span> sağ paneldeki veya kenar çubuğundaki kutudan projeleriniz hakkında soru sorabilirsiniz.</p>
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

  return (
    <div className="flex h-full">
      <Sidebar />
      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopNav onMenu={() => setDrawerOpen(true)} />
        <main className="flex-1 overflow-y-auto pb-20 lg:pb-0">
          <div className="mx-auto max-w-[1400px] p-4 lg:p-6">
            <Outlet />
          </div>
        </main>
      </div>
      <MobileNav />
    </div>
  );
}

// Page header helper
export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold text-primary">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-text-secondary">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
