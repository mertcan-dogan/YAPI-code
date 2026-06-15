import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { Toaster } from "./components/Toaster";
import { useAuth } from "./store/auth";

import AIAlertsPage from "./pages/AIAlertsPage";
import AIAssistantPage from "./pages/AIAssistantPage";
import ApprovalsPage from "./pages/ApprovalsPage";
import AuditLogPage from "./pages/AuditLogPage";
import BudgetPage from "./pages/BudgetPage";
import CashFlowPage from "./pages/CashFlowPage";
import DashboardPage from "./pages/DashboardPage";
import DocumentCapturePage from "./pages/DocumentCapturePage";
import EquipmentPage from "./pages/EquipmentPage";
import InvoicesPage from "./pages/InvoicesPage";
import LoginPage from "./pages/LoginPage";
import NewProjectPage from "./pages/NewProjectPage";
import ProjectDashboardPage from "./pages/ProjectDashboardPage";
import ProjectsListPage from "./pages/ProjectsListPage";
import RemindersPage from "./pages/RemindersPage";
import ReportsPage from "./pages/ReportsPage";
import SettingsPage from "./pages/SettingsPage";
import SubcontractorsPage from "./pages/SubcontractorsPage";
import TwoFactorSetupPage from "./pages/TwoFactorSetupPage";
import VariationsPage from "./pages/VariationsPage";
import VendorsPage from "./pages/VendorsPage";
import WorkspacePage from "./pages/WorkspacePage";

function FullScreenLoader() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
    </div>
  );
}

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const [mfaOk, setMfaOk] = useState(true);

  // CR-002-I 10.1: directors must enrol in 2FA when enforcement is enabled.
  useEffect(() => {
    const enforce = import.meta.env.VITE_REQUIRE_DIRECTOR_MFA === "1";
    if (!enforce || !user || user.role !== "director") return;
    import("./lib/supabase").then(async ({ supabase }) => {
      const { data } = await supabase.auth.mfa.listFactors();
      const verified = (data?.totp ?? []).some((f: any) => f.status === "verified");
      setMfaOk(verified);
    });
  }, [user]);

  if (loading) return <FullScreenLoader />;
  if (!user) return <Navigate to="/login" replace />;
  if (!mfaOk && window.location.pathname !== "/2fa-setup") return <Navigate to="/2fa-setup" replace />;
  return <>{children}</>;
}

export default function App() {
  const init = useAuth((s) => s.init);
  useEffect(() => {
    init();
  }, [init]);

  return (
    <BrowserRouter>
      <Toaster />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <Protected>
              <AppLayout />
            </Protected>
          }
        >
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/projects" element={<ProjectsListPage />} />
          <Route path="/projects/new" element={<NewProjectPage />} />
          <Route path="/projects/:id/dashboard" element={<ProjectDashboardPage />} />
          <Route path="/projects/:id/budget" element={<BudgetPage />} />
          <Route path="/projects/:id/invoices" element={<InvoicesPage />} />
          <Route path="/projects/:id/variations" element={<VariationsPage />} />
          <Route path="/projects/:id/subcontractors" element={<SubcontractorsPage />} />
          <Route path="/projects/:id/cashflow" element={<CashFlowPage />} />
          <Route path="/projects/:id/equipment" element={<EquipmentPage />} />
          <Route path="/projects/:id/audit-log" element={<AuditLogPage />} />
          <Route path="/audit-log" element={<AuditLogPage />} />
          <Route path="/reminders" element={<RemindersPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/ai-alerts" element={<AIAlertsPage />} />
          <Route path="/ai-assistant" element={<AIAssistantPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/vendors" element={<VendorsPage />} />
          <Route path="/document-capture" element={<DocumentCapturePage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/settings/*" element={<SettingsPage />} />
          <Route path="/2fa-setup" element={<TwoFactorSetupPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
