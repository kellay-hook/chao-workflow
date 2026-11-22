import { useEffect, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useSession } from './store'
import AppShell from './components/AppShell'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import VerifyPage from './pages/VerifyPage'
import AcceptInvitePage from './pages/AcceptInvitePage'
import DashboardPage from './pages/DashboardPage'
import WorkflowsPage from './pages/WorkflowsPage'
import WorkflowEditorPage from './pages/WorkflowEditorPage'
import WorkflowCreatePage from './pages/WorkflowCreatePage'
import RunsPage from './pages/RunsPage'
import RunDetailPage from './pages/RunDetailPage'
import ApprovalsPage from './pages/ApprovalsPage'
import KnowledgePage from './pages/KnowledgePage'
import AgentsPage from './pages/AgentsPage'
import ToolsPage from './pages/ToolsPage'
import PluginsPage from './pages/PluginsPage'
import SettingsPage from './pages/SettingsPage'

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useSession()
  if (loading) return <div className="p-8 text-sm text-slate-500">加载中…</div>
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  const { bootstrap, user, loading } = useSession()
  useEffect(() => {
    void bootstrap()
  }, [])
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/register" element={user ? <Navigate to="/" replace /> : <RegisterPage />} />
      <Route path="/verify" element={<VerifyPage />} />
      <Route path="/accept-invite" element={<AcceptInvitePage />} />
      <Route
        path="/"
        element={
          <Protected>
            <AppShell />
          </Protected>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="workflows" element={<WorkflowsPage />} />
        <Route path="workflows/new" element={<WorkflowCreatePage />} />
        <Route path="workflows/:id" element={<WorkflowEditorPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:id" element={<RunDetailPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="plugins" element={<PluginsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to={loading ? '/login' : '/'} replace />} />
    </Routes>
  )
}
