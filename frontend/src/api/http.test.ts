import { afterEach, describe, expect, test, vi } from 'vitest'
import { mockFetch } from '../test/helpers'
import { ApiError, request, setAdminTokenGetter } from './http'

afterEach(() => {
  vi.unstubAllGlobals()
  setAdminTokenGetter(async () => null)
})

describe('request', () => {
  test('sends the admin token by default and an explicit token when given', async () => {
    setAdminTokenGetter(async () => 'admin-jwt')
    const { calls } = mockFetch({ 'GET /clients': { body: [] }, 'GET /portal/onboarding': { body: {} } })
    await request('/clients')
    await request('/portal/onboarding', { token: 'portal-session' })
    expect(calls[0].headers.Authorization).toBe('Bearer admin-jwt')
    expect(calls[1].headers.Authorization).toBe('Bearer portal-session')
  })

  test('token: null sends nothing, which the exchange needs', async () => {
    setAdminTokenGetter(async () => 'admin-jwt')
    const { calls } = mockFetch({ 'POST /portal/exchange': { body: { session: 's', expires_in: 1800 } } })
    await request('/portal/exchange', { body: { token: 'x' }, token: null })
    expect(calls[0].headers.Authorization).toBeUndefined()
    expect(calls[0].body).toEqual({ token: 'x' })
  })

  test('keeps the server\'s own wording and every problem it listed', async () => {
    mockFetch({ 'PUT /portal/steps/a': { status: 422, body: { detail: 'The answer has problems.', problems: ['Name: this is required.', 'Email: bad'] } } })
    const e = await request('/portal/steps/a', { method: 'PUT', body: {}, token: 't' }).catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e).toMatchObject({ status: 422, message: 'The answer has problems.', problems: ['Name: this is required.', 'Email: bad'] })
  })

  test('reads Retry-After on a 429', async () => {
    mockFetch({ 'POST /portal/exchange': { status: 429, body: { detail: 'Too many requests.' }, headers: { 'Retry-After': '42' } } })
    const e = await request('/portal/exchange', { body: {}, token: null }).catch((x) => x)
    expect(e).toMatchObject({ status: 429, retryAfter: 42 })
  })

  test('a framework validation error becomes a plain sentence, never raw JSON', async () => {
    mockFetch({ 'POST /clients': { status: 422, body: { detail: [{ type: 'string_too_short', loc: ['body', 'name'] }] } } })
    const e = (await request('/clients', { body: {} }).catch((x) => x)) as ApiError
    expect(e.message).toBe('Some of what was sent is not valid.')
  })

  test('an unreachable server says so in plain words', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const e = (await request('/clients').catch((x) => x)) as ApiError
    expect(e).toMatchObject({ status: 0 })
    expect(e.message).toMatch(/Can't reach the server/)
  })

  test('text responses come back as text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('name: x\n', { status: 200 })))
    expect(await request<string>('/templates/1/export', { text: true })).toBe('name: x\n')
  })
})
