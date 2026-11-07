import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { AdminStep, Client, OnboardingDetail } from '../api/types'
import { mockFetch, renderRoute } from '../test/helpers'
import OnboardingDetailPage from './OnboardingDetail'
import StepResponse from './StepResponse'
import TemplatesPage from './TemplatesPage'

afterEach(() => vi.unstubAllGlobals())

function astep(over: Partial<AdminStep> = {}): AdminStep {
  return {
    id: 's1', key: 'basics', type: 'form', title: 'Basics', section: '', position: 0, visibility: 'client', status: 'pending', assignee_contact_id: null,
    due_at: null, completed_at: null, config: {}, response: null, revisions: 0, files: [], comments: [], ...over,
  }
}
const resp = (data: Record<string, any>, by = 'contact:c1') => ({ revision: 1, data, submitted_by: by, submitted_at: '2026-11-07T10:00:00Z' })

describe('StepResponse', () => {
  test('a form answer reads as labels and values, never JSON', () => {
    const step = astep({
      config: { fields: [{ key: 'name', label: 'Business name', type: 'text' }, { key: 'tools', label: 'Tools', type: 'multiselect' }, { key: 'agree', label: 'I agree', type: 'checkbox' }] },
      response: resp({ answers: { name: 'Acme', tools: ['a', 'b'], agree: true } }),
    })
    render(<StepResponse onboardingId="o1" step={step} />)
    expect(screen.getByText('Business name').nextSibling).toHaveTextContent('Acme')
    expect(screen.getByText('Tools').nextSibling).toHaveTextContent('a, b')
    expect(screen.getByText('I agree').nextSibling).toHaveTextContent('Yes')
    expect(screen.getByText(/by the client/)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('{')
  })

  test('connect, book call, approval and internal notes in words', () => {
    const cases: [Partial<AdminStep>, RegExp][] = [
      [{ type: 'connect', response: resp({ status: 'connected', account_label: 'Acme GBP' }) }, /Connected: Acme GBP/],
      [{ type: 'connect', response: resp({ status: 'pending' }) }, /asked for help/],
      [{ type: 'book_call', response: resp({ booked: true }) }, /Booked/],
      [{ type: 'approval', response: resp({ decision: 'approved' }) }, /Approved/],
      [{ type: 'approval', response: resp({ decision: 'changes_requested', comment: 'Warmer' }) }, /Changes requested: "Warmer"/],
      [{ type: 'internal_task', response: resp({ note: 'Built it' }, 'admin:jay@x.test') }, /Built it/],
    ]
    for (const [over, re] of cases) {
      const { unmount } = render(<StepResponse onboardingId="o1" step={astep(over)} />)
      expect(document.body.textContent).toMatch(re)
      unmount()
    }
  })

  test('no answer yet says so; revisions are shown', () => {
    const { unmount } = render(<StepResponse onboardingId="o1" step={astep()} />)
    expect(screen.getByText('No answer yet.')).toBeInTheDocument()
    unmount()
    render(<StepResponse onboardingId="o1" step={astep({ type: 'connect', revisions: 3, response: { ...resp({ status: 'connected', account_label: 'x' }), revision: 3 } })} />)
    expect(screen.getByText(/version 3 of 3/)).toBeInTheDocument()
  })

  test('an uploaded file offers a download that asks the server for a short-lived link', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    mockFetch({ 'GET /onboardings/o1/files/f1/url': { body: { name: 'logo.png', url: 'https://store.test/signed?exp=600' } } })
    const step = astep({ type: 'upload', response: resp({ file_ids: ['f1'] }), files: [{ id: 'f1', name: 'logo.png', size: 2048 }] })
    render(<StepResponse onboardingId="o1" step={step} />)
    await userEvent.click(screen.getByRole('button', { name: 'Download' }))
    await waitFor(() => expect(open).toHaveBeenCalledWith('https://store.test/signed?exp=600', '_blank', 'noopener,noreferrer'))
    open.mockRestore()
  })
})

describe('TemplatesPage', () => {
  const list = { 'GET /templates': { body: [{ id: 't1', name: 'Trades', slug: 'trades', current_version: 2, archived: false }] } }

  test('lists templates with their version', async () => {
    mockFetch(list)
    renderRoute(<TemplatesPage />, '/', '/')
    expect(await screen.findByText(/version 2/)).toBeInTheDocument()
  })

  test('"Check it" shows every problem and saves nothing', async () => {
    const { calls } = mockFetch({ ...list, 'POST /templates/import': { body: { ok: false, problems: ["layout: 'grid' is not one of ['focus', 'checklist']", 'steps: [] should be non-empty'] } } })
    renderRoute(<TemplatesPage />, '/', '/')
    await userEvent.type(screen.getByLabelText('Template YAML'), 'name: x')
    await userEvent.click(screen.getByRole('button', { name: 'Check it' }))
    expect(await screen.findByText(/'grid' is not one of/)).toBeInTheDocument()
    expect(screen.getByText(/should be non-empty/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/templates/import')!.body).toMatchObject({ dry_run: true })
  })

  test('saving says whether a new version was made', async () => {
    mockFetch({ ...list, 'POST /templates/import': { body: { ok: true, problems: [], new_version: false } } })
    renderRoute(<TemplatesPage />, '/', '/')
    await userEvent.type(screen.getByLabelText('Template YAML'), 'name: x')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/Nothing changed, so no new version was made/)).toBeInTheDocument()
  })

  test('buttons stay off until there is something to check', () => {
    mockFetch(list)
    renderRoute(<TemplatesPage />, '/', '/')
    expect(screen.getByRole('button', { name: 'Check it' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })
})

describe('OnboardingDetail', () => {
  const client: Client = {
    id: 'cl1', name: 'Acme Plumbing', kind: 'trades', status: 'active', notes: '', created_at: '2026-11-01T00:00:00Z',
    contacts: [{ id: 'c1', client_id: 'cl1', name: 'Pat Owner', email: '', phone: '', role: 'owner', sms_consent: false, sms_consent_source: '' }],
  }
  const draft: OnboardingDetail = {
    id: 'o1', client_id: 'cl1', title: 'Kickoff: Acme', layout: 'focus', status: 'draft', started_at: null, completed_at: null,
    last_activity_at: '2026-11-07T00:00:00Z', nudges_paused: false, progress: { done: 0, total: 2 },
    steps: [astep({ id: 's1', key: 'basics', title: 'Basics' }), astep({ id: 's2', key: 'build', title: 'Build the agent', type: 'internal_task', visibility: 'internal' })],
  }
  const base = { 'GET /clients': { body: [client] }, 'GET /onboardings/o1/links': { body: [] } }
  const at = (ui = <OnboardingDetailPage />) => renderRoute(ui, '/onboardings/:id', '/onboardings/o1')

  test('a draft says the client can see nothing yet, and internal steps are marked as never shown', async () => {
    mockFetch({ ...base, 'GET /onboardings/o1': { body: draft } })
    at()
    expect(await screen.findByText(/The client can't see anything until you send it/)).toBeInTheDocument()
    expect(screen.getByText(/Internal\. Never shown to the client/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send to the client' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull()
  })

  test('with nobody to send to, sending is off and it says why', async () => {
    mockFetch({ 'GET /clients': { body: [{ ...client, contacts: [] }] }, 'GET /onboardings/o1': { body: draft }, 'GET /onboardings/o1/links': { body: [] } })
    at()
    expect(await screen.findByText(/no contacts yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send to the client' })).toBeDisabled()
  })

  test('sending shows each link once with a warning that it cannot be shown again', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const sent = { ...draft, status: 'active', links: [{ id: 'l1', contact_id: 'c1', contact_name: 'Pat Owner', expires_at: '2026-12-07T00:00:00Z', revoked_at: null, last_used_at: null, usable: true, url: 'https://onboard.test/c/SECRET-TOKEN-123' }] }
    mockFetch({ ...base, 'GET /onboardings/o1': { body: draft }, 'POST /onboardings/o1/send': { body: sent } })
    at()
    await userEvent.click(await screen.findByRole('button', { name: 'Send to the client' }))
    const input = (await screen.findByLabelText('Link for Pat Owner')) as HTMLInputElement
    expect(input.value).toBe('https://onboard.test/c/SECRET-TOKEN-123')
    expect(screen.getByText(/They can't be shown again/)).toBeInTheDocument()
    vi.mocked(window.confirm).mockRestore()
  })

  test('the links list never contains a raw link, only status and dates', async () => {
    const links = [
      { id: 'l1', contact_id: 'c1', contact_name: 'Pat Owner', expires_at: '2026-12-07T00:00:00Z', revoked_at: null, last_used_at: null, usable: true },
      { id: 'l2', contact_id: 'c1', contact_name: 'Pat Owner', expires_at: '2026-10-01T00:00:00Z', revoked_at: null, last_used_at: null, usable: false },
      { id: 'l3', contact_id: 'c1', contact_name: 'Pat Owner', expires_at: '2026-12-07T00:00:00Z', revoked_at: '2026-11-02T00:00:00Z', last_used_at: null, usable: false },
    ]
    mockFetch({ 'GET /clients': { body: [client] }, 'GET /onboardings/o1': { body: { ...draft, status: 'active' } }, 'GET /onboardings/o1/links': { body: links } })
    at()
    const panel = await screen.findByRole('region', { name: 'Client links' })
    expect(await within(panel).findByText(/Works/)).toBeInTheDocument()
    expect(within(panel).getByText(/Expired/)).toBeInTheDocument()
    expect(within(panel).getByText(/Revoked/)).toBeInTheDocument()
    expect(within(panel).queryByRole('textbox')).toBeNull()
    expect(within(panel).getAllByRole('button', { name: 'Revoke' }).length).toBe(2) // not offered for the one already revoked
  })

  test('revoking asks first, then calls the server', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const link = { id: 'l1', contact_id: 'c1', contact_name: 'Pat Owner', expires_at: '2026-12-07T00:00:00Z', revoked_at: null, last_used_at: null, usable: true }
    const { calls } = mockFetch({
      'GET /clients': { body: [client] }, 'GET /onboardings/o1': { body: { ...draft, status: 'active' } }, 'GET /onboardings/o1/links': { body: [link] },
      'POST /onboardings/o1/links/l1/revoke': { body: { ...link, revoked_at: '2026-11-07T00:00:00Z', usable: false } },
    })
    at()
    await userEvent.click(await screen.findByRole('button', { name: 'Revoke' }))
    expect(calls.some((c) => c.path.endsWith('/revoke'))).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/revoke'))).toBe(true))
    confirm.mockRestore()
  })

  test('a private comment is saved as hidden from the client', async () => {
    const { calls } = mockFetch({
      ...base, 'GET /onboardings/o1': { body: { ...draft, status: 'active' } },
      'POST /onboardings/o1/steps/build/comments': { status: 201, body: { id: 'x', author_kind: 'admin', author_label: 'me', body: 'note', client_visible: false, created_at: '2026-11-07T00:00:00Z' } },
    })
    at()
    await userEvent.type(await screen.findByLabelText('Add a private comment'), 'call the supplier')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(calls.find((c) => c.path.endsWith('/build/comments'))?.body).toEqual({ body: 'call the supplier', client_visible: false }))
  })
})
