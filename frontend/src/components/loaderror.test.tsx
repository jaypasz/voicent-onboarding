import { screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/http'
import { mockFetch, renderRoute } from '../test/helpers'
import OnboardingsPage from '../admin/OnboardingsPage'
import { diagnose } from './LoadError'

afterEach(() => vi.unstubAllGlobals())

const local = { localMode: true }
const real = { localMode: false, userId: 'b3f1c2d4-1111-2222-3333-444455556666' }

test('a 401 on a build with no Supabase settings names the two build variables and says a restart is not enough', () => {
  const d = diagnose(new ApiError(401, 'Sign in required.'), local)
  const text = [d.title, ...d.steps].join(' ')
  expect(text).toMatch(/VITE_SUPABASE_URL/)
  expect(text).toMatch(/VITE_SUPABASE_ANON_KEY/)
  expect(text).toMatch(/restart is not enough/)
})

test('a 401 when sign-in is configured points at the server-side key settings', () => {
  const text = diagnose(new ApiError(401, 'Invalid or expired session.'), real).steps.join(' ')
  expect(text).toMatch(/SUPABASE_JWKS_URL/)
  expect(text).toMatch(/SUPABASE_JWT_SECRET/)
})

test('a 403 gives the exact seed command with the signed-in user id filled in', () => {
  const d = diagnose(new ApiError(403, "Your account isn't a member of any organization."), real)
  expect(d.title).toMatch(/isn't linked to an organization/)
  expect(d.steps[0]).toContain('python -m app.cli seed')
  expect(d.steps[0]).toContain('--admin-user-id b3f1c2d4-1111-2222-3333-444455556666')
})

test('server errors point at the logs and the database; no answer means no connection', () => {
  const s500 = diagnose(new ApiError(500, 'x'), real)
  expect(s500.title).toContain('status 500')
  expect(s500.steps.join(' ')).toMatch(/DATABASE_URL/)
  expect(diagnose(new ApiError(0, "Can't reach the server."), real).title).toMatch(/didn't answer/)
})

test('anything else keeps the server\'s own wording', () => {
  expect(diagnose(new ApiError(404, 'Client not found.'), real).title).toBe('Client not found.')
  expect(diagnose(new Error('boom'), real).title).toBe('Something went wrong.')
})

test('the onboardings page shows the cause instead of a bare "couldn\'t load"', async () => {
  mockFetch({
    'GET /onboardings': { status: 401, body: { detail: 'Sign in required.' } },
    'GET /clients': { status: 401, body: { detail: 'Sign in required.' } },
  })
  renderRoute(<OnboardingsPage />, '/', '/')
  expect(await screen.findByText(/Couldn't load onboardings\./)).toBeInTheDocument()
  expect(await screen.findByText(/built without sign-in settings/)).toBeInTheDocument()
  expect(screen.queryByText(/Nothing here yet/)).toBeNull() // an error is not "no data"
})
