import { create } from 'zustand'
import { authApi, tenantApi } from './api'
import { getTenantId, getToken, setTenantId, setToken } from './session'
import type { AuthResponse, RoleInfo, Tenant, User } from './types'

type SessionState = {
  user: User | null
  tenants: Tenant[]
  activeTenant: Tenant | null
  role: string | null
  permissions: string[]
  roles: RoleInfo[]
  canManageMembers: boolean
  invitableRoles: string[]
  loading: boolean
  error: string | null
  setSession: (data: AuthResponse) => void
  bootstrap: () => Promise<void>
  switchTenant: (tenantId: string) => Promise<void>
  refreshPermissions: () => Promise<void>
  can: (permission: string) => boolean
  logout: () => Promise<void>
  clear: () => void
}

export const useSession = create<SessionState>((set, get) => ({
  user: null,
  tenants: [],
  activeTenant: null,
  role: null,
  permissions: [],
  roles: [],
  canManageMembers: false,
  invitableRoles: [],
  loading: true,
  error: null,
  setSession: (data) => {
    setToken(data.access_token)
    const tenantId = data.active_tenant?.id ?? data.tenants[0]?.id ?? null
    setTenantId(tenantId)
    set({
      user: data.user,
      tenants: data.tenants,
      activeTenant: data.active_tenant ?? data.tenants[0] ?? null,
      loading: false,
      error: null,
    })
    void get().refreshPermissions()
  },
  bootstrap: async () => {
    if (!getToken()) {
      set({ loading: false })
      return
    }
    try {
      const data = await authApi.me()
      const storedTenant = getTenantId()
      const active =
        data.tenants.find((tenant) => tenant.id === storedTenant) ??
        data.tenants.find((tenant) => tenant.id === data.active_tenant_id) ??
        data.tenants[0] ??
        null
      setTenantId(active?.id ?? null)
      set({ user: data.user, tenants: data.tenants, activeTenant: active, loading: false, error: null })
      await get().refreshPermissions()
    } catch {
      setToken(null)
      setTenantId(null)
      set({ user: null, tenants: [], activeTenant: null, loading: false })
    }
  },
  switchTenant: async (tenantId) => {
    const data = await authApi.switchTenant(tenantId)
    get().setSession(data)
    await get().refreshPermissions()
  },
  refreshPermissions: async () => {
    const tenantId = get().activeTenant?.id ?? getTenantId()
    if (!tenantId) {
      set({ role: null, permissions: [], roles: [], canManageMembers: false, invitableRoles: [] })
      return
    }
    try {
      const data = await tenantApi.permissions()
      set({
        role: data.role,
        permissions: data.permissions,
        roles: data.roles,
        canManageMembers: data.can_manage_members,
        invitableRoles: data.invitable_roles,
      })
    } catch {
      set({ role: null, permissions: [], roles: [], canManageMembers: false, invitableRoles: [] })
    }
  },
  can: (permission) => {
    const permissions = get().permissions
    return permissions.includes('*') || permissions.includes(permission)
  },
  logout: async () => {
    try {
      await authApi.logout()
    } catch {
      /* ignore */
    }
    get().clear()
  },
  clear: () => {
    setToken(null)
    setTenantId(null)
    set({
      user: null,
      tenants: [],
      activeTenant: null,
      role: null,
      permissions: [],
      roles: [],
      canManageMembers: false,
      invitableRoles: [],
      loading: false,
    })
  },
}))