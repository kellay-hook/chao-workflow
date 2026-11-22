const TOKEN_KEY = 'flowmind_token'
const TENANT_KEY = 'flowmind_tenant'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export function getTenantId(): string | null {
  return localStorage.getItem(TENANT_KEY)
}

export function setTenantId(tenantId: string | null) {
  if (tenantId) localStorage.setItem(TENANT_KEY, tenantId)
  else localStorage.removeItem(TENANT_KEY)
}
