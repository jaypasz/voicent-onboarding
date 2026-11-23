import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { AuditEntry } from '../api/types'
import { ACTIVITY_PAGE } from '../api/admin'
import { mockFetch, renderRoute } from '../test/helpers'
import OnboardingActivityPage from './OnboardingActivityPage'

const entry = (over: Partial<AuditEntry> = {}): AuditEntry => ({
  id: Math.random().toString(36).slice(2), at: '2026-11-20T15:00:00Z', actor_kind: 'team', actor_label: 'Morgan', action: 'step.completed',
  step_key: 'basics', summary: 'Marked “Company basics” done.', about_client: false, ...over,
})
const first = `GET /onboardings/o1/activity?limit=${ACTIVITY_PAGE}`

describe('the Activity tab', () => {
  test('shows who did what and when, grouped by day, with the kind of actor in words', async () => {
    mockFetch({
      [first]: { body: [
        entry({ id: 'a', at: '2026-11-21T16:00:00Z', actor_kind: 'client', actor_label: 'Pat Owner', summary: '“Company basics”: filled it in.' }),
        entry({ id: 'b', at: '2026-11-20T15:00:00Z' }),
        entry({ id: 'c', at: '2026-11-20T14:00:00Z', actor_kind: 'system', actor_label: 'Reminders', summary: 'Sent automatic reminder 1 to Pat Owner by text.' }),
        entry({ id: 'd', at: '2026-11-20T13:00:00Z', summary: 'Marked Acme Plumbing as paying.', about_client: true }),
      ] },
    })
    renderRoute(<OnboardingActivityPage />, '/onboardings/:id/activity', '/onboardings/o1/activity')
    expect(await screen.findByRole('heading', { name: 'Activity' })).toBeInTheDocument()
    const days = screen.getAllByRole('heading', { level: 3 })
    expect(days).toHaveLength(2)
    const later = screen.getByRole('region', { name: days[0].textContent! })
    expect(within(later).getByText('Pat Owner')).toBeInTheDocument()
    expect(within(later).getByText('(client)')).toBeInTheDocument()
    expect(screen.getByText('(system)')).toBeInTheDocument()
    expect(screen.getByText('Client record')).toBeInTheDocument()
    expect(screen.getByText(/can't be edited or deleted/)).toBeInTheDocument()
  })

  test('filters by who acted', async () => {
    mockFetch({ [first]: { body: [entry({ id: 'a', actor_kind: 'client', actor_label: 'Pat Owner' }), entry({ id: 'b', actor_label: 'Morgan' })] } })
    renderRoute(<OnboardingActivityPage />, '/onboardings/:id/activity', '/onboardings/o1/activity')
    await screen.findByText('Pat Owner')
    await userEvent.selectOptions(screen.getByLabelText('Show'), 'client')
    expect(screen.getByText('Pat Owner')).toBeInTheDocument()
    expect(screen.queryByText('Morgan')).toBeNull()
  })

  test('a full page offers older entries, asked for before the last one shown', async () => {
    const page = Array.from({ length: ACTIVITY_PAGE }, (_, i) => entry({ id: `p${i}`, at: new Date(Date.UTC(2026, 10, 20, 12, 0, 0) - i * 1000).toISOString() }))
    const last = page[page.length - 1].at
    const { calls } = mockFetch({
      [first]: { body: page },
      [`${first}&before=${encodeURIComponent(last)}`]: { body: [entry({ id: 'old', summary: 'Created this onboarding from the template “Mini” (version 1).' })] },
    })
    renderRoute(<OnboardingActivityPage />, '/onboardings/:id/activity', '/onboardings/o1/activity')
    await userEvent.click(await screen.findByRole('button', { name: 'Show older' }))
    expect(await screen.findByText(/Created this onboarding/)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Show older' })).toBeNull())
    expect(calls).toHaveLength(2)
  })

  test('an empty trail says so', async () => {
    mockFetch({ [first]: { body: [] } })
    renderRoute(<OnboardingActivityPage />, '/onboardings/:id/activity', '/onboardings/o1/activity')
    expect(await screen.findByText('Nothing recorded yet.')).toBeInTheDocument()
  })

  test('a load error is shown, not an empty trail', async () => {
    mockFetch({ [first]: { status: 500, body: { detail: 'boom' } } })
    renderRoute(<OnboardingActivityPage />, '/onboardings/:id/activity', '/onboardings/o1/activity')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText('Nothing recorded yet.')).toBeNull()
  })
})
