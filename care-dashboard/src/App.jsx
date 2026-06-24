import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import CallDetailPage from "./pages/CallDetailPage";
import DashboardPage from "./pages/Dashboardpage";
import LoginPage from "./pages/LoginPage";
import ReportsPage from "./pages/ReportsPage";
import SettingsPage from "./pages/SettingsPage";
import UploadPage from "./pages/UploadPage";
import KpiTrackerPage from "./pages/KpiTrackerPage";
import AdminUsersPage from "./pages/AdminUsersPage";
import CrmUsagePage from "./pages/CrmUsagePage";
import Navbar from "./components/Navbar";
import Sidebar from "./components/Sidebar";
import { hasPermission, getStoredUser } from "./utils/permissions";
import { getMe } from "./services/api";

function RequirePerm({ perm, user, children }) {
  if (!hasPermission(user, perm)) {
    return <Navigate to="/dashboard" replace />;
  }
  return children;
}

export default function App() {
  const [user, setUser] = useState(() => getStoredUser());
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("care_token");
    if (!token) {
      setBooting(false);
      return;
    }
    getMe()
      .then((data) => {
        const merged = { ...getStoredUser(), ...data, permissions: data.permissions || [] };
        localStorage.setItem("care_user", JSON.stringify(merged));
        setUser(merged);
      })
      .catch(() => {
        localStorage.removeItem("care_token");
        localStorage.removeItem("care_user");
        setUser(null);
      })
      .finally(() => setBooting(false));
  }, []);

  const handleLogin = (userData) => {
    setUser(userData);
  };

  const handleUserUpdate = (updated) => {
    const merged = { ...user, ...updated };
    localStorage.setItem("care_user", JSON.stringify(merged));
    setUser(merged);
  };

  const handleLogout = () => {
    localStorage.removeItem("care_token");
    localStorage.removeItem("care_user");
    setUser(null);
  };

  if (booting) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center text-slate-400">
        Loading…
      </div>
    );
  }

  if (!user) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <BrowserRouter>
      <div className="flex h-screen bg-gray-950 text-white overflow-hidden">
        <Sidebar user={user} onLogout={handleLogout} />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Navbar user={user} onLogout={handleLogout} />
          <main className="flex-1 overflow-y-auto">
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={
                <RequirePerm perm="dashboard_view" user={user}><DashboardPage /></RequirePerm>
              } />
              <Route path="/kpis" element={
                <RequirePerm perm="agent_performance" user={user}><KpiTrackerPage /></RequirePerm>
              } />
              <Route path="/upload" element={
                <RequirePerm perm="upload_calls" user={user}><UploadPage /></RequirePerm>
              } />
              <Route path="/reports" element={
                <RequirePerm perm="view_reports" user={user}><ReportsPage /></RequirePerm>
              } />
              <Route path="/settings" element={
                <SettingsPage user={user} onUserUpdate={handleUserUpdate} />
              } />
              <Route path="/admin/users" element={
                <RequirePerm perm="manage_users" user={user}><AdminUsersPage onSessionExpired={handleLogout} /></RequirePerm>
              } />
              <Route path="/admin/crm-usage" element={
                <RequirePerm perm="crm_usage" user={user}><CrmUsagePage /></RequirePerm>
              } />
              <Route path="/calls/:callId" element={
                <RequirePerm perm="view_call_details" user={user}><CallDetailPage /></RequirePerm>
              } />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
