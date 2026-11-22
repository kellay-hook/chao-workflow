import type { ReactNode } from 'react'
import { ShieldCheck } from 'lucide-react'
import { useSession } from '../store'

const roleStyles: Record<string, string> = {
  owner: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
  admin: 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200',
  editor: 'bg-sky-50 text-sky-700 ring-1 ring-sky-200',
  runner: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
  viewer: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',
}

const fallbackNames: Record<string, string> = {
  owner: '所有者',
  admin: '管理员',
  editor: '编辑者',
  runner: '运行者',
  viewer: '查看者',
}

export function roleName(role: string | null | undefined, roles: { id: string; name: string }[] = []) {
  if (!role) return '未分配'
  return roles.find((item) => item.id === role)?.name || fallbackNames[role] || role
}

export function RoleBadge({ role, roles: provided, showIcon = false }: { role?: string | null; roles?: { id: string; name: string }[]; showIcon?: boolean }) {
  const storeRole = useSession((state) => state.role)
  const storeRoles = useSession((state) => state.roles)
  const effectiveRole = role ?? storeRole
  const effectiveRoles = provided ?? storeRoles
  return (
    <span className={`badge ${roleStyles[effectiveRole || 'viewer'] || roleStyles.viewer}`}>
      {showIcon && <ShieldCheck size={11} />}
      {roleName(effectiveRole, effectiveRoles)}
    </span>
  )
}

export function Can({
  permission,
  children,
  fallback = null,
}: {
  permission: string
  children: ReactNode
  fallback?: ReactNode
}) {
  const permissions = useSession((state) => state.permissions)
  const allowed = permissions.includes('*') || permissions.includes(permission)
  return <>{allowed ? children : fallback}</>
}

export function useCan(permission: string) {
  const permissions = useSession((state) => state.permissions)
  return permissions.includes('*') || permissions.includes(permission)
}