import { expect, type APIRequestContext, type Page } from '@playwright/test'

export const DEMO_EMAIL = 'demo@flowmind.dev'
export const DEMO_PASSWORD = 'password123'

export async function login(page: Page) {
  await page.goto('/login')
  await page.locator('input[type=email]').fill(DEMO_EMAIL)
  await page.locator('input[type=password]').fill(DEMO_PASSWORD)
  await page.locator('form button[type=submit]').click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: /你好，/ })).toBeVisible()
}

export async function apiAuth(request: APIRequestContext) {
  const response = await request.post('/api/v1/auth/login', {
    data: { email: DEMO_EMAIL, password: DEMO_PASSWORD },
  })
  expect(response.ok()).toBeTruthy()
  const data = await response.json()
  return {
    headers: { Authorization: `Bearer ${data.access_token}` },
    tenantId: data.active_tenant.id as string,
  }
}

export async function deleteKnowledgeBase(
  request: APIRequestContext,
  auth: { headers: Record<string, string>; tenantId: string },
  kbId: string,
) {
  await request.delete(`/api/v1/tenants/${auth.tenantId}/knowledge-bases/${kbId}`, {
    headers: auth.headers,
  })
}

export async function deleteWorkflow(
  request: APIRequestContext,
  auth: { headers: Record<string, string>; tenantId: string },
  workflowId: string,
) {
  await request.delete(`/api/v1/tenants/${auth.tenantId}/workflows/${workflowId}`, {
    headers: auth.headers,
  })
}

export async function findKnowledgeBase(
  request: APIRequestContext,
  auth: { headers: Record<string, string>; tenantId: string },
  name: string,
) {
  const response = await request.get(`/api/v1/tenants/${auth.tenantId}/knowledge-bases`, {
    headers: auth.headers,
  })
  const items = (await response.json()) as { id: string; name: string }[]
  return items.find((item) => item.name === name)
}

export async function findWorkflow(
  request: APIRequestContext,
  auth: { headers: Record<string, string>; tenantId: string },
  name: string,
) {
  const response = await request.get(`/api/v1/tenants/${auth.tenantId}/workflows`, {
    headers: auth.headers,
  })
  const items = (await response.json()) as { id: string; name: string }[]
  return items.find((item) => item.name === name)
}