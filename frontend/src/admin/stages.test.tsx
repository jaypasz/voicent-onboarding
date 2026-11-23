import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { AdminStage, AdminStep, OnboardingDetail, PortalStep } from '../api/types'
import ChecklistLayout from '../portal/ChecklistLayout'
import FocusLayout, { nextOpenIndex } from '../portal/FocusLayout'
import { PortalScreen } from '../portal/PortalPage'
import { mockFetch, renderRoute, step as portalStep, view } from '../test/helpers'
import OnboardingDetailPage from './OnboardingDetail'

const step = (over: Partial<AdminStep> = {}): AdminStep => ({
  id: 's1', key: 'about', type: 'form', title: 'About you', section: 'discover', position: 0, visibility: 'client', status: 'done', assignee_contact_id: null,
  team_assignee_id: null, due_at: null, completed_at: null, config: { fields: [] }, response: null, revisions: 0, files: [], comments: [], ...over,
})
const stage = (over: Partial<AdminStage> = {}): AdminStage => ({
  key: 'discover', title: 'Discovery', signoff: true, state: 'ready', signed_by: null, signed_at: null, progress: { done: 1, total: 1 },
  start_on: null, due_on: null, ...over,
})
const detail = (over: Partial<OnboardingDetail> = {}): OnboardingDetail => ({
  id: 'o1', client_id: 'cl1', title: 'Kickoff', layout: 'checklist', status: 'active', started_at: null, completed_at: null,
  last_activity_at: '2026-11-07T00:00:00Z', nudges_paused: false, attention: null, provision_state: null, owner_member_id: null,
  progress: { done: 1, total: 2 },
  stages: [stage(), stage({ key: 'build', title: 'Build', state: 'locked', progress: { done: 0, total: 1 }, start_on: '2026-12-01', due_on: '2026-12-05' })],
  steps: [step(), step({ id: 's2', key: 'assets', title: 'Assets', section: 'build', status: 'pending', locked: true, start_on: '2026-12-01', due_on: '2026-12-05' })],
  ...over,
})
const base = { 'GET /clients': { body: [] }, 'GET /team': { body: { members: [], invites: [], linked: false, in_sync: true, can_manage: false } } }

describe('stages on the overview', () => {
  test('each stage shows its title, where it stands, and a sign-off when it is ready', async () => {
    const { calls } = mockFetch({
      ...base, 'GET /org': { body: { role: 'manager' } }, 'GET /onboardings/o1': { body: detail() },
      'POST /onboardings/o1/stages/discover/signoff': { body: detail() },
    })
    renderRoute(<OnboardingDetailPage />, '/onboardings/:id', '/onboardings/o1')
    const discovery = await screen.findByRole('region', { name: /Discovery/ })
    expect(within(discovery).getByText('Ready for sign-off')).toBeInTheDocument()
    const build = screen.getByRole('region', { name: /Build/ })
    expect(within(build).getByText('Not open yet')).toBeInTheDocument()
    expect(within(build).getByText(/can't answer them until “Discovery” is signed off/)).toBeInTheDocument()
    expect(within(build).getByText('🔒 Not open to the client yet')).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Stages' })).getAllByRole('listitem')).toHaveLength(2)

    await userEvent.click(within(discovery).getByRole('button', { name: 'Sign off “Discovery”' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/onboardings/o1/stages/discover/signoff')).toBe(true))
  })

  test('a member sees the stage is ready but the button is for an admin or a manager', async () => {
    mockFetch({ ...base, 'GET /org': { body: { role: 'member' } }, 'GET /onboardings/o1': { body: detail() } })
    renderRoute(<OnboardingDetailPage />, '/onboardings/:id', '/onboardings/o1')
    expect(await screen.findByText(/An admin or a manager signs it off/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign off “Discovery”' })).toBeDisabled()
  })

  test('a signed-off stage says who and can be withdrawn', async () => {
    const signed = detail({ stages: [stage({ state: 'signed_off', signed_by: 'Morgan', signed_at: '2026-11-20T15:00:00Z' })], steps: [step()] })
    mockFetch({ ...base, 'GET /org': { body: { role: 'admin' } }, 'GET /onboardings/o1': { body: signed } })
    renderRoute(<OnboardingDetailPage />, '/onboardings/:id', '/onboardings/o1')
    expect(await screen.findByText(/Signed off by Morgan/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Withdraw sign-off' })).toBeInTheDocument()
    expect(screen.queryByText(/get a message shortly/)).not.toBeInTheDocument()
  })

  test('the overview says when the client is about to hear a stage opened', async () => {
    mockFetch({ ...base, 'GET /org': { body: { role: 'admin' } }, 'GET /onboardings/o1': { body: detail({ stage_notice_pending: true }) } })
    renderRoute(<OnboardingDetailPage />, '/onboardings/:id', '/onboardings/o1')
    expect(await screen.findByText(/get a message shortly saying the next stage is open/)).toBeInTheDocument()
  })

  test('a step gets its start and due day from a calendar, saved as days', async () => {
    const { calls } = mockFetch({
      ...base, 'GET /org': { body: { role: 'admin' } }, 'GET /onboardings/o1': { body: detail() },
      'PUT /onboardings/o1/steps/assets/schedule': { body: {} },
    })
    renderRoute(<OnboardingDetailPage />, '/onboardings/:id', '/onboardings/o1')
    await userEvent.click(await screen.findByRole('button', { name: /Assets/ }))
    const due = screen.getByLabelText('Due')
    expect(due).toHaveAttribute('type', 'date')
    expect(due).toHaveValue('2026-12-05')
    expect(screen.getByLabelText('Starts')).toHaveAttribute('max', '2026-12-05')
    await userEvent.clear(due)
    await userEvent.type(due, '2026-12-09')
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT').at(-1)?.body).toEqual({ start_on: '2026-12-01', due_on: '2026-12-09' }))
    expect(calls.filter((c) => c.method === 'PUT').every((c) => c.body.due_on === null || Number(c.body.due_on.slice(0, 4)) >= 2000)).toBe(true)
    expect(screen.getByRole('region', { name: /Build/ })).toHaveTextContent('Dec 1, 2026 – Dec 5, 2026'.replace(/ /g, ' '))
  })
})

describe('stages in the portal', () => {
  const locked: PortalStep = portalStep({ key: 'assets', title: 'Assets', section: 'build', locked: true, can_write: false })
  const doneStep: PortalStep = portalStep({ key: 'about', title: 'About you', section: 'discover', status: 'done' })

  test('a locked step is never where the focus layout takes the client', () => {
    expect(nextOpenIndex([doneStep, locked], -1)).toBe(-1)
    expect(nextOpenIndex([doneStep, locked], -1, true)).toBe(-1)  // the preview too
  })

  test('with only locked steps left, the client hears the next part opens after our review', () => {
    renderRoute(<FocusLayout view={view({ layout: 'focus', steps: [doneStep, locked] })} onChanged={async () => {}} />, '/', '/')
    expect(screen.getByText(/That's this part done/)).toBeInTheDocument()
    expect(screen.getByText(/next part opens once we've signed it off/)).toBeInTheDocument()
  })

  test('the checklist marks a stage waiting on us and one not open yet, and says why a step is read-only', async () => {
    const v = view({
      sections: [{ key: 'discover', title: 'Discovery' }, { key: 'build', title: 'Build' }],
      stages: [{ key: 'discover', title: 'Discovery', signoff: true, state: 'waiting' }, { key: 'build', title: 'Build', signoff: true, state: 'locked' }],
      steps: [doneStep, locked],
    })
    renderRoute(<ChecklistLayout view={v} onChanged={async () => {}} />, '/', '/')
    expect(screen.getByText('With us for review')).toBeInTheDocument()
    expect(screen.getByText('Opens once we have reviewed the part before')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Assets/ }))
    expect(screen.getByRole('note')).toHaveTextContent('This opens once we have reviewed the part before it')
  })

  test('the portal tracker shows stages when there are some', () => {
    const v = view({ stages: [{ key: 'discover', title: 'Discovery', signoff: true, state: 'open' }], sections: [{ key: 'discover', title: 'Discovery' }], steps: [portalStep({ section: 'discover' })] })
    renderRoute(<PortalScreen view={v} onChanged={async () => {}} />, '/', '/')
    const tracker = screen.getByRole('list', { name: 'Your stages' })
    expect(within(tracker).getByText('Discovery')).toBeInTheDocument()
    expect(within(tracker).getByText('In progress')).toBeInTheDocument()
  })
})
