import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { Client, OnboardingDetail, OnboardingSummary } from '../api/types'
import { mockFetch, renderRoute } from '../test/helpers'
import AiosPanel from './AiosPanel'
import ClientDetail from './ClientDetail'
import OnboardingDetailPage from './OnboardingDetail'
import OnboardingsPage from './OnboardingsPage'
import RemindersPanel from './RemindersPanel'

afterEach(() => vi.unstubAllGlobals())

const ob = (over: Partial<OnboardingDetail> = {}): OnboardingDetail => ({
  id: 'o1', client_id: 'cl1', title: 'Kickoff: Acme', layout: 'checklist', status: 'active', started_at: '2026-11-01T00:00:00Z', completed_at: null,
  last_activity_at: '2026-11-07T00:00:00Z', nudges_paused: false, attention: null, progress: { done: 1, total: 3 }, steps: [], ...over,
})
const features = (over = {}) => ({ sms: true, email: true, reminders: true, aios_sync: true, uploads: false, jobs: true, ...over })
const synced = { enabled: true, state: 'synced', project_id: 'onb-o1', log: [] }

describe('RemindersPanel', () => {
  test('says plainly when reminders are off and why, and does not offer to send', async () => {
    mockFetch({ 'GET /features': { body: features({ reminders: false, sms: false, email: false }) }, 'GET /onboardings/o1/nudges': { body: [] } })
    renderRoute(<RemindersPanel ob={ob()} />, '/', '/')
    expect(await screen.findByText(/Reminders are off/)).toBeInTheDocument()
    expect(screen.getByText(/APP_URL/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send a reminder now' })).toBeDisabled()
  })

  test('sending now shows what happened to each person in words, with a glyph', async () => {
    const { calls } = mockFetch({
      'GET /features': { body: features() }, 'GET /onboardings/o1/nudges': { body: [] },
      'POST /onboardings/o1/nudge': { body: { message: '', results: [
        { contact: 'Pat Owner', status: 'sent', channel: 'sms', reason: '' },
        { contact: 'Ivy IT', status: 'skipped', channel: null, reason: "There's no email address or consented phone number to reach them on." },
        { contact: 'Sam', status: 'later', channel: null, reason: "It's night where they are." },
        { contact: 'Kim', status: 'failed', channel: 'email', reason: 'The email service refused it (status 500).' },
      ] } },
    })
    renderRoute(<RemindersPanel ob={ob()} />, '/', '/')
    const btn = await screen.findByRole('button', { name: 'Send a reminder now' })
    await waitFor(() => expect(btn).toBeEnabled())
    await userEvent.click(btn)
    const list = await screen.findByRole('list', { name: 'Result' })
    const items = within(list).getAllByRole('listitem').map((li) => li.textContent!.replace(/\s+/g, ' '))
    expect(items[0]).toContain('✓ Sent Pat Owner by text message')
    expect(items[1]).toContain("– Couldn't send Ivy IT")
    expect(items[1]).toContain('no email address or consented phone number')
    expect(items[2]).toContain('◐ Will try later Sam')
    expect(items[3]).toContain('✕ Failed Kim by email')
    expect(calls.some((c) => c.method === 'POST' && c.path === '/onboardings/o1/nudge')).toBe(true)
  })

  test('nobody with steps left is said in words', async () => {
    mockFetch({ 'GET /features': { body: features() }, 'GET /onboardings/o1/nudges': { body: [] }, 'POST /onboardings/o1/nudge': { body: { results: [], message: 'Nobody has any steps left to do.' } } })
    renderRoute(<RemindersPanel ob={ob()} />, '/', '/')
    const btn = await screen.findByRole('button', { name: 'Send a reminder now' })
    await waitFor(() => expect(btn).toBeEnabled())
    await userEvent.click(btn)
    expect(await screen.findByText('Nobody has any steps left to do.')).toBeInTheDocument()
  })

  test('a server refusal is shown, not swallowed', async () => {
    mockFetch({ 'GET /features': { body: features() }, 'GET /onboardings/o1/nudges': { body: [] }, 'POST /onboardings/o1/nudge': { status: 409, body: { detail: 'Only an active onboarding can be reminded.' } } })
    renderRoute(<RemindersPanel ob={ob()} />, '/', '/')
    const btn = await screen.findByRole('button', { name: 'Send a reminder now' })
    await waitFor(() => expect(btn).toBeEnabled())
    await userEvent.click(btn)
    expect(await screen.findByRole('alert')).toHaveTextContent('Only an active onboarding can be reminded.')
  })

  test('only an active onboarding can be reminded, and it says so', async () => {
    mockFetch({ 'GET /features': { body: features() }, 'GET /onboardings/o1/nudges': { body: [] } })
    renderRoute(<RemindersPanel ob={ob({ status: 'paused' })} />, '/', '/')
    expect(await screen.findByText(/Reminders only go to active onboardings/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send a reminder now' })).toBeDisabled()
  })

  test('the switch for automatic reminders saves straight away', async () => {
    const { calls } = mockFetch({ 'GET /features': { body: features() }, 'GET /onboardings/o1/nudges': { body: [] }, 'PUT /onboardings/o1/nudges': { body: ob({ nudges_paused: true }) } })
    renderRoute(<RemindersPanel ob={ob()} />, '/', '/')
    await userEvent.click(await screen.findByLabelText(/Don't remind this client automatically/))
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ paused: true }))
  })

  test('the switch flips at once, and puts itself back with a message if the save fails', async () => {
    let answer!: () => void
    const held = new Promise<void>((resolve) => (answer = resolve))
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
      if (String(url).endsWith('/features')) return json(features())
      if ((init.method ?? 'GET') === 'PUT') {
        await held // the server is slow to answer
        return json({ detail: 'Something went wrong.' }, 500)
      }
      return json([])
    }))
    renderRoute(<RemindersPanel ob={ob()} />, '/', '/')
    const box = (await screen.findByLabelText(/Don't remind this client automatically/)) as HTMLInputElement
    await userEvent.click(box)
    expect(box.checked).toBe(true) // at once, while the server has not answered
    answer()
    await waitFor(() => expect(box.checked).toBe(false)) // and back again when it was refused
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong.')
  })

  test('the history says who, how, whether it was automatic, and what went wrong', async () => {
    mockFetch({ 'GET /features': { body: features() }, 'GET /onboardings/o1/nudges': { body: [
      { id: 'n1', contact: 'Pat Owner', channel: 'sms', status: 'sent', round: 1, kind: 'stalled', at: '2026-11-04T15:00:00Z', error: '' },
      { id: 'n2', contact: 'Ivy IT', channel: 'email', status: 'failed', round: 2, kind: 'manual', at: '2026-11-05T15:00:00Z', error: 'The email service refused it (status 500).' },
    ] } })
    renderRoute(<RemindersPanel ob={ob()} />, '/', '/')
    const list = await screen.findByRole('list', { name: 'Reminder history' })
    const rows = within(list).getAllByRole('listitem').map((li) => li.textContent!.replace(/\s+/g, ' '))
    expect(rows[0]).toContain('✓ Sent Pat Owner by text message')
    expect(rows[0]).toContain('automatic')
    expect(rows[1]).toContain('✕ Failed Ivy IT by email')
    expect(rows[1]).toContain('sent by you')
    expect(rows[1]).toContain('status 500')
  })
})

describe('AiosPanel', () => {
  const state = (over = {}) => ({ body: { ...synced, ...over } })

  test.each([
    ['synced', '✓', 'Up to date'],
    ['pending', '◐', 'Waiting to sync'],
    ['failing', '✕', "Isn't syncing"],
    ['not_sent', '○', 'Not started'],
  ])('%s is shown with a glyph and a word', async (st, glyph, word) => {
    mockFetch({ 'GET /features': { body: features() }, 'GET /onboardings/o1/sync': state({ state: st }) })
    renderRoute(<AiosPanel ob={ob()} />, '/', '/')
    const badge = await screen.findByText(word)
    expect(badge.closest('.badge')!.textContent).toContain(glyph)
  })

  test('when it is off it names the settings and offers no button', async () => {
    mockFetch({ 'GET /features': { body: features({ aios_sync: false }) }, 'GET /onboardings/o1/sync': state({ enabled: false, state: 'off', project_id: null }) })
    renderRoute(<AiosPanel ob={ob()} />, '/', '/')
    expect(await screen.findByText(/AIOS_API_URL and AIOS_SERVICE_TOKEN/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sync now' })).toBeNull()
  })

  test('a draft with sync off shows nothing at all', async () => {
    mockFetch({ 'GET /features': { body: features({ aios_sync: false }) }, 'GET /onboardings/o1/sync': state({ enabled: false, state: 'off', project_id: null }) })
    const { container } = renderRoute(<AiosPanel ob={ob({ status: 'draft' })} />, '/', '/')
    await waitFor(() => expect(container.querySelector('section')).toBeNull())
  })

  test('the last problem is shown, and "Sync now" reports how it went', async () => {
    const { calls } = mockFetch({
      'GET /features': { body: features() },
      'GET /onboardings/o1/sync': state({ state: 'failing', log: [{ at: '2026-11-07T01:00:00Z', status: 'failed', detail: "AIOS didn't answer (update task, status 502)." }] }),
      'POST /onboardings/o1/sync': state({ state: 'synced', result: { ok: true, state: 'synced', message: 'AIOS is up to date.', changes: 2 } }),
    })
    renderRoute(<AiosPanel ob={ob()} />, '/', '/')
    expect(await screen.findByText(/AIOS didn't answer \(update task, status 502\)/)).toBeInTheDocument()
    expect(screen.getByLabelText('Recent sync activity').textContent).toContain('✕ Failed')
    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }))
    expect(await screen.findByText('AIOS is up to date.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path === '/onboardings/o1/sync')).toBe(true)
  })

  test('a failed manual sync says so with the reason', async () => {
    mockFetch({
      'GET /features': { body: features() }, 'GET /onboardings/o1/sync': state(),
      'POST /onboardings/o1/sync': state({ state: 'failing', result: { ok: false, state: 'failed', message: 'AIOS refused it (update task, status 403).', changes: 0 } }),
    })
    renderRoute(<AiosPanel ob={ob()} />, '/', '/')
    await userEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('status 403')
  })
})

describe('the list and the detail page flag an onboarding that needs you', () => {
  const summary = (over: Partial<OnboardingSummary>): OnboardingSummary => ({ ...ob(), ...over })
  const client = (over: Partial<Client> = {}): Client => ({ id: 'cl1', name: 'Acme', kind: 'trades', status: 'active', notes: '', timezone: 'America/New_York', created_at: '2026-11-01T00:00:00Z', contacts: [], ...over })

  test('each reason is a word as well as a badge', async () => {
    mockFetch({
      'GET /onboardings': { body: [summary({ id: 'a', title: 'Quiet one', attention: 'nudges_exhausted' }), summary({ id: 'b', title: 'Lost one', attention: 'unreachable' }), summary({ id: 'c', title: 'Fine one' })] },
      'GET /clients': { body: [client()] },
    })
    renderRoute(<OnboardingsPage />, '/', '/')
    expect(await screen.findByText(/Needs you: no reply to the reminders/)).toBeInTheDocument()
    expect(screen.getByText(/Needs you: no way to reach them/)).toBeInTheDocument()
    expect(screen.getAllByText(/Needs you/).length).toBe(2)
  })

  test('the detail page explains it, and for an unreachable client links to the page where it is fixed', async () => {
    mockFetch({
      'GET /onboardings/o1': { body: ob({ attention: 'unreachable' }) }, 'GET /clients': { body: [client()] }, 'GET /onboardings/o1/links': { body: [] },
      'GET /features': { body: features() }, 'GET /onboardings/o1/nudges': { body: [] }, 'GET /onboardings/o1/sync': state(),
    })
    renderRoute(<OnboardingDetailPage />, '/onboardings/:id', '/onboardings/o1')
    const banner = (await screen.findByText(/no email address or consented phone number to reach this client/)).closest('.banner')!
    expect(within(banner as HTMLElement).getByRole('link', { name: /Add one on the client page/ })).toHaveAttribute('href', '/clients/cl1')
  })

  function state() { return { body: synced } }
})

describe('ClientDetail time zone', () => {
  const client: Client = { id: 'cl1', name: 'Acme', kind: 'trades', status: 'active', notes: '', timezone: 'America/Chicago', created_at: '2026-11-01T00:00:00Z', contacts: [] }

  test('shows the current zone and saves a new one', async () => {
    const { calls } = mockFetch({ 'GET /clients': { body: [client] }, 'GET /onboardings': { body: [] }, 'PATCH /clients/cl1': { body: { ...client, timezone: 'America/Denver' } } })
    renderRoute(<ClientDetail />, '/clients/:id', '/clients/cl1')
    const select = (await screen.findByLabelText(/Their time zone/)) as HTMLSelectElement
    expect(select.value).toBe('America/Chicago')
    await userEvent.selectOptions(select, 'America/Denver')
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ timezone: 'America/Denver' }))
    expect(screen.getByText(/never sent at night here/)).toBeInTheDocument()
  })

  test('a zone that is not in the short list is kept, not lost', async () => {
    mockFetch({ 'GET /clients': { body: [{ ...client, timezone: 'Europe/Berlin' }] }, 'GET /onboardings': { body: [] } })
    renderRoute(<ClientDetail />, '/clients/:id', '/clients/cl1')
    expect(((await screen.findByLabelText(/Their time zone/)) as HTMLSelectElement).value).toBe('Europe/Berlin')
  })
})
