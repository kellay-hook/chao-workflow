import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Bot,
  Boxes,
  CheckSquare,
  Database,
  LayoutDashboard,
  LogOut,
  Menu,
  PlayCircle,
  Puzzle,
  Settings,
  Workflow,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { useSession } from '../store'
import { RoleBadge } from './permissions'

const links = [
  { to: '/', label: '概览', icon: LayoutDashboard, end: true },
  { to: '/workflows', label: '工作流', icon: Workflow },
  { to: '/runs', label: '运行记录', icon: PlayCircle },
  { to: '/approvals', label: '审批中心', icon: CheckSquare },
  { to: '/knowledge', label: '知识库', icon: Database },
  { to: '/agents', label: 'Agent', icon: Bot },
  { to: '/tools', label: '工具 / MCP', icon: Boxes },
  { to: '/plugins', label: '插件', icon: Puzzle },
]

export default function AppShell() {
  const { user, tenants, activeTenant, role, roles, switchTenant, logout } = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  const initials = useMemo(() => (user?.name || user?.email || 'F').slice(0, 1).toUpperCase(), [user])

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-slate-200/70 bg-white/85 backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-[1600px] items-center gap-3 px-4 sm:px-6 lg:px-8">
          <button
            className="rounded-xl border border-slate-200 bg-white p-2 text-slate-600 shadow-sm min-[1400px]:hidden"
            onClick={() => setMobileOpen((value) => !value)}
            aria-label="打开导航"
          >
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
          </button>

          <button className="flex shrink-0 items-center gap-2.5 text-left" onClick={() => navigate('/')}>
            <span className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-lg font-bold text-white shadow-lg shadow-indigo-200/80">F</span>
            <span className="hidden sm:block">
              <span className="block text-[15px] font-semibold tracking-[-0.01em] text-slate-950">FlowMind</span>
              <span className="block text-[9px] font-bold uppercase tracking-[0.18em] text-slate-400">AI Workspace</span>
            </span>
          </button>

          <nav className="ml-2 hidden items-center gap-1 rounded-2xl bg-slate-100/70 p-1 ring-1 ring-slate-200/60 min-[1400px]:flex">
            {links.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx(
                    'inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl px-2.5 py-2 text-[12px] font-semibold transition',
                    isActive
                      ? 'bg-white text-indigo-700 shadow-sm ring-1 ring-indigo-100'
                      : 'text-slate-500 hover:bg-white/80 hover:text-slate-900',
                  )
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold text-emerald-700 2xl:inline-flex">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> 服务正常
            </span>
            <select
              className="h-9 max-w-[160px] rounded-xl border border-slate-200 bg-white px-3 text-[12px] font-medium text-slate-700 shadow-sm outline-none focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100"
              value={activeTenant?.id ?? ''}
              onChange={async (event) => {
                if (event.target.value) await switchTenant(event.target.value)
              }}
              aria-label="切换工作空间"
            >
              {tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </select>
            <NavLink
              to="/settings"
              aria-label="设置"
              title="设置"
              className={({ isActive }) =>
                clsx(
                  'grid h-9 w-9 place-items-center rounded-xl border text-slate-500 transition',
                  isActive ? 'border-indigo-200 bg-indigo-50 text-indigo-600' : 'border-slate-200 bg-white hover:bg-slate-50 hover:text-slate-800',
                )
              }
            >
              <Settings size={16} />
            </NavLink>
            <div className="hidden items-center gap-2 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 shadow-sm md:flex">
              <span className="grid h-6 w-6 place-items-center rounded-full bg-gradient-to-br from-slate-500 to-slate-700 text-[10px] font-bold text-white">{initials}</span>
              <span className="min-w-0">
                <span className="block max-w-[110px] truncate text-[11px] font-semibold leading-tight text-slate-600">{user?.name || user?.email}</span>
                <RoleBadge role={role} roles={roles} />
              </span>
            </div>
            <button
              title="退出登录"
              aria-label="退出登录"
              className="grid h-9 w-9 place-items-center rounded-xl border border-slate-200 bg-white text-slate-400 shadow-sm transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600"
              onClick={async () => {
                await logout()
                navigate('/login')
              }}
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>

        {mobileOpen && (
          <div className="border-t border-slate-200/70 bg-white px-4 pb-4 pt-3 sm:px-6 min-[1400px]:hidden">
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {links.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px] font-semibold transition',
                      isActive ? 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-100' : 'text-slate-600 hover:bg-slate-50',
                    )
                  }
                >
                  <Icon size={15} /> {label}
                </NavLink>
              ))}
              <NavLink
                to="/settings"
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px] font-semibold transition',
                    isActive ? 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-100' : 'text-slate-600 hover:bg-slate-50',
                  )
                }
              >
                <Settings size={15} /> 设置
              </NavLink>
            </div>
          </div>
        )}
      </header>

      <main className="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <Outlet />
      </main>
    </div>
  )
}