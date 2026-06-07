import { cn } from "@/lib/cn";
import { useAuth } from "@/store/auth";
import {
  BarChart3,
  Bell,
  Calculator,
  FileBarChart,
  FileText,
  FolderKanban,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Settings,
  Sparkles,
  TrendingUp,
  Users,
  Wrench,
} from "lucide-react";
import * as React from "react";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";

const GLOBAL_NAV = [
  { icon: LayoutDashboard, label: "Ana Sayfa", to: "/dashboard" },
  { icon: FolderKanban, label: "Projeler", to: "/projects" },
];

const PROJECT_NAV = (id: string) => [
  { icon: BarChart3, label: "Proje Özeti", to: `/projects/${id}/dashboard` },
  { icon: Calculator, label: "Bütçe & Maliyetler", to: `/projects/${id}/budget` },
  { icon: FileText, label: "Faturalar & Hakediş", to: `/projects/${id}/invoices` },
  { icon: Users, label: "Alt Yükleniciler", to: `/projects/${id}/subcontractors` },
  { icon: TrendingUp, label: "Nakit Akışı", to: `/projects/${id}/cashflow` },
  { icon: Wrench, label: "Ekipman", to: `/projects/${id}/equipment` },
];

const BOTTOM_NAV = [
  { icon: Bell, label: "Hatırlatıcılar", to: "/reminders" },
  { icon: FileBarChart, label: "Raporlar", to: "/reports" },
  { icon: Sparkles, label: "Yapay Zeka Uyarıları", to: "/ai-alerts" },
  { icon: Settings, label: "Ayarlar", to: "/settings" },
];

function NavItem({ icon: Icon, label, to, active }: any) {
  return (
    <Link
      to={to}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
        active ? "bg-primary-light text-white" : "text-white/70 hover:bg-primary-light/60 hover:text-white"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{label}</span>
    </Link>
  );
}

function Sidebar() {
  const { pathname } = useLocation();
  const params = useParams();
  const projectId = params.id;
  const isDirector = useAuth((s) => s.user?.role === "director");
  return (
    <aside className="hidden w-64 shrink-0 flex-col bg-primary lg:flex">
      <div className="flex items-center gap-2 px-5 py-4 text-white">
        <div className="flex h-8 w-8 items-center justify-center rounded bg-accent font-bold text-primary">Y</div>
        <span className="text-lg font-bold">Yapı</span>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {GLOBAL_NAV.map((n) => (
          <NavItem key={n.to} {...n} active={pathname === n.to} />
        ))}
        {projectId && (
          <div className="mt-3 border-t border-white/10 pt-3">
            <p className="px-3 pb-1 text-[10px] uppercase tracking-wide text-white/40">Proje</p>
            {PROJECT_NAV(projectId).map((n) => (
              <NavItem key={n.to} {...n} active={pathname === n.to} />
            ))}
            {/* CR-001-H: Denetim İzi — director only, under Ekipman */}
            {isDirector && (
              <NavItem
                icon={History}
                label="Denetim İzi"
                to={`/projects/${projectId}/audit-log`}
                active={pathname === `/projects/${projectId}/audit-log`}
              />
            )}
          </div>
        )}
        <div className="mt-3 border-t border-white/10 pt-3">
          {BOTTOM_NAV.map((n) => (
            <NavItem key={n.to} {...n} active={pathname.startsWith(n.to)} />
          ))}
          {isDirector && (
            <NavItem icon={History} label="Denetim İzi" to="/audit-log" active={pathname === "/audit-log"} />
          )}
        </div>
      </nav>
    </aside>
  );
}

function TopNav() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  return (
    <header className="flex h-16 items-center justify-between border-b border-border bg-surface px-4 lg:px-6">
      <div className="flex items-center gap-3">
        <Menu className="h-5 w-5 text-text-secondary lg:hidden" />
        <span className="font-semibold text-primary lg:hidden">Yapı</span>
      </div>
      <div className="relative flex items-center gap-3">
        <Link to="/reminders" className="text-text-secondary hover:text-primary">
          <Bell className="h-5 w-5" />
        </Link>
        <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-sm font-medium text-white">
            {user?.full_name?.charAt(0) ?? "K"}
          </div>
          <span className="hidden text-sm text-text-primary sm:block">{user?.full_name}</span>
        </button>
        {open && (
          <div className="absolute right-0 top-12 w-48 rounded-md border border-border bg-surface py-1 shadow-lg">
            <div className="border-b border-border px-3 py-2 text-xs text-text-secondary">{user?.email}</div>
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
    </header>
  );
}

function MobileNav() {
  const { pathname } = useLocation();
  const items = [
    { icon: LayoutDashboard, label: "Ana Sayfa", to: "/dashboard" },
    { icon: FolderKanban, label: "Projeler", to: "/projects" },
    { icon: Plus, label: "Maliyet", to: "/projects" },
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
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopNav />
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
