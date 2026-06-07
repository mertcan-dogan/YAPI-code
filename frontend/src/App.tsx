import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { Toaster } from "./components/Toaster";
import { useAuth } from "./store/auth";

import AIAlertsPage from "./pages/AIAlertsPage";
import AuditLogPage from "./pages/AuditLogPage";
import BudgetPage from "./pages/BudgetPage";
import CashFlowPage from "./pages/CashFlowPage";
import DashboardPage from "./pages/DashboardPage";
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

function FullScreenLoader() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
    </div>
  );
}

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <FullScreenLoader />;
  if (!user) return <Navigate to="/login" replace />;
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
          <Route path="/projects/:id/subcontractors" element={<SubcontractorsPage />} />
          <Route path="/projects/:id/cashflow" element={<CashFlowPage />} />
          <Route path="/projects/:id/equipment" element={<EquipmentPage />} />
          <Route path="/projects/:id/audit-log" element={<AuditLogPage />} />
          <Route path="/audit-log" element={<AuditLogPage />} />
          <Route path="/reminders" element={<RemindersPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/ai-alerts" element={<AIAlertsPage />} />
          <Route path="/settings/*" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
