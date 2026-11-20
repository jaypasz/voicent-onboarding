import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { AdminStep, OnboardingDetail, OnboardingSummary, Team } from '../api/types'
import { mockFetch, renderRoute } from '../test/helpers'
import NotificationsPage from './NotificationsPage'
import OnboardingDetailPage from './OnboardingDetail'
import OnboardingsPage from './OnboardingsPage'
import TeamPage from './TeamPage'

afterEach(() => vi.restoreAllMocks())

const team = (over: Partial<Team> = {}): Team => ({
  linked: false, in_sync: true, can_manage: true, me: 'm-jay', invites: [],
  members: [
    { id: 'm-jay', email: 'jay@bakery.test', name: '', role: 'admin', source: 'local', is_you: true, notify_email: true },
    { id: 'm-kim', email: 'kim@bakery.test', name: 'Kim', role: 'member', source: 'local', is_you: false, notify_email: null },
  ], ...over,
})

describe('Team', () => {
  test('a linked team says people come from Voicent-App and offers no invites or role changes', async () => {
    mockFetch({ 'GET /team': { body: team({ linked: true, can_manage: false, members: team().members.map((m) => ({ ...m, source: 'voicent' })) }) } })
    renderRoute(<TeamPage />, '/team', '/team')
    expect(await screen.findByText(/Your team comes from Voicent-App/)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Invite someone' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull()
  })

  test('an admin invites by email and changes a role', async () => {
    const { calls } = mockFetch({ 'GET /team': { body: team() }, 'POST /team/invites': { status: 201, body: {} }, 'PATCH /team/members/m-kim': { body: {} } })
    renderRoute(<TeamPage />, '/team', '/team')
    await userEvent.type(await screen.findByLabelText('Their email'), 'lu@bakery.test')
    await userEvent.selectOptions(screen.getByLabelText('Role'), 'manager')
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }))
    expect(await screen.findByText(/They join when they sign in as lu@bakery.test/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/team/invites')!.body).toEqual({ email: 'lu@bakery.test', role: 'manager' })
    await userEvent.selectOptions(screen.getByLabelText('Role for Kim'), 'viewer')
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ role: 'viewer' }))
  })

  test('you choose whether you also get emails', async () => {
    const { calls } = mockFetch({ 'GET /team': { body: team() }, 'PUT /team/me': { body: {} } })
    renderRoute(<TeamPage />, '/team', '/team')
    await userEvent.click(await screen.findByLabelText(/Also email me/))
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ notify_email: false }))
  })
})

describe('Notifications', () => {
  test('new ones are marked as new in words, open their onboarding, and can all be marked read', async () => {
    const items = [
      { id: 'n1', kind: 'step_done', text: 'Pat answered “Basics” in “Mini: Shop”.', onboarding_id: 'o1', step_key: 'basics', read: false, created_at: '2026-11-20T00:00:00Z' },
      { id: 'n2', kind: 'completed', text: '“Old” is finished.', onboarding_id: 'o2', step_key: '', read: true, created_at: '2026-11-19T00:00:00Z' },
    ]
    const { calls } = mockFetch({ 'GET /notifications': { body: { unread: 1, items } }, 'POST /notifications/read': { body: { marked: 1 } } })
    renderRoute(<NotificationsPage />, '/notifications', '/notifications')
    const list = await screen.findByRole('list', { name: 'Notifications' })
    expect(within(list).getAllByText(/New|Read/).map((e) => e.textContent?.trim())).toEqual(['● New', '○ Read'])
    expect(within(list).getByRole('link', { name: /Pat answered/ })).toHaveAttribute('href', '/onboardings/o1')
    await userEvent.click(screen.getByRole('button', { name: 'Mark all as read' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({}))
  })
})

describe('assigning', () => {
  const step = (over: Partial<AdminStep> = {}): AdminStep => ({
    id: 's1', key: 'basics', type: 'form', title: 'Basics', section: '', position: 0, visibility: 'client', status: 'pending', assignee_contact_id: null,
    team_assignee_id: null, due_at: null, completed_at: null, config: { fields: [] }, response: { revision: 1, data: {}, submitted_by: 'x', submitted_at: '2026-11-07T00:00:00Z' },
    revisions: 1, files: [], comments: [], ...over,
  } as AdminStep)
  const ob: OnboardingDetail = {
    id: 'o1', client_id: 'cl1', title: 'Mini: Shop', layout: 'checklist', status: 'active', started_at: null, completed_at: null,
    last_activity_at: '2026-11-07T00:00:00Z', nudges_paused: false, attention: null, provision_state: null, owner_member_id: 'm-jay',
    progress: { done: 0, total: 1 }, steps: [step()],
  }

  test('the owner and who follows a step up are chosen on the overview', async () => {
    const { calls } = mockFetch({
      'GET /onboardings/o1': { body: ob }, 'GET /clients': { body: [] }, 'GET /team': { body: team() },
      'PUT /onboardings/o1/owner': { body: { ...ob, owner_member_id: 'm-kim' } }, 'PUT /onboardings/o1/steps/basics/team-assignee': { body: {} },
    })
    renderRoute(<OnboardingDetailPage />, '/onboardings/:id', '/onboardings/o1')
    const owner = await screen.findByLabelText('Looked after by')
    await waitFor(() => expect(owner).toHaveValue('m-jay'))
    await userEvent.selectOptions(owner, 'm-kim')
    await waitFor(() => expect(calls.find((c) => c.path === '/onboardings/o1/owner')?.body).toEqual({ member_id: 'm-kim' }))
    await userEvent.selectOptions(screen.getByLabelText('Followed up by (our side)'), 'm-kim')
    await waitFor(() => expect(calls.find((c) => c.path.endsWith('/team-assignee'))?.body).toEqual({ member_id: 'm-kim' }))
  })

  test('"only the ones I look after" asks the server for yours', async () => {
    const summary = { ...ob, steps: undefined } as unknown as OnboardingSummary
    const { calls } = mockFetch({ 'GET /onboardings': { body: [summary] }, 'GET /onboardings?mine=1': { body: [] }, 'GET /clients': { body: [] }, 'GET /team': { body: team() } })
    renderRoute(<OnboardingsPage />, '/', '/')
    expect(await screen.findByText(/looked after by you/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Only the ones I look after'))
    expect(await screen.findByText("You don't look after any onboardings.")).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/onboardings?mine=1')).toBe(true)
  })
})
