import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { Client, OnboardingDetail } from '../api/types'
import { textOn } from '../lib/brand'
import { PortalScreen } from '../portal/PortalPage'
import { mockFetch, renderRoute, step, view } from '../test/helpers'
import ClientDetail from './ClientDetail'
import OnboardingPreviewPage from './OnboardingPreviewPage'
import SettingsPage from './SettingsPage'
import VoicentPanel from './VoicentPanel'

const BRAND = { name: 'Acme Agency', logo_url: 'https://cdn.acme.test/logo.png', primary_color: '#aa3300', accent_color: null }

afterEach(() => vi.restoreAllMocks())

describe('brand colours', () => {
  test('text on a brand colour is whichever of white or near-black reads better', () => {
    expect(textOn('#aa3300')).toBe('#ffffff')
    expect(textOn('#ffe066')).toBe('#0b0b0b')
  })
})

describe('the client portal under a reseller brand', () => {
  test('shows their logo and colours, and the team is them, never Voicent', async () => {
    const v = view({
      brand: BRAND, layout: 'checklist',
      steps: [step({ comments: [{ id: 'k', author_kind: 'admin', author_label: 'jay@voicent.test', body: 'Welcome aboard', created_at: '2026-11-07T00:00:00Z' }] })],
    })
    renderRoute(<PortalScreen view={v} onChanged={async () => undefined} />, '/', '/')
    const logo = await screen.findByRole('img', { name: 'Acme Agency' })
    expect(logo).toHaveAttribute('src', 'https://cdn.acme.test/logo.png')
    expect(document.querySelector('main.portal')).toHaveStyle({ '--accent': '#aa3300' })
    expect(await screen.findByText(/Acme Agency ·/)).toBeInTheDocument() // the first open step is shown, with its comment
    expect(document.body.textContent).not.toMatch(/Voicent/)
  })

  test('a logo that is not plain https is not shown', async () => {
    renderRoute(<PortalScreen view={view({ brand: { ...BRAND, logo_url: 'javascript:alert(1)' } })} onChanged={async () => undefined} />, '/', '/')
    expect(await screen.findByText('Acme Agency')).toBeInTheDocument()
    expect(screen.queryByRole('img')).toBeNull()
  })
})

describe('client preview', () => {
  const pv = (over = {}) => ({
    body: { ...view({ brand: BRAND, status: 'draft', steps: [step({ can_write: false })] }), preview: true,
      contacts: [{ id: 'c1', name: 'Pat Owner', role: 'owner' }, { id: 'c2', name: 'Ivy IT', role: 'it' }], ...over },
  })

  test('shows the branded client screen for a chosen contact, read-only, even for a draft', async () => {
    const { calls } = mockFetch({ 'GET /onboardings/o1/preview': pv(), 'GET /onboardings/o1/preview?contact_id=c2': pv({ contact: { id: 'c2', name: 'Ivy IT' } }) })
    renderRoute(<OnboardingPreviewPage />, '/onboardings/:id/preview', '/onboardings/o1/preview')
    const frame = await screen.findByRole('region', { name: 'Client preview' })
    expect(within(frame).getByRole('img', { name: 'Acme Agency' })).toBeInTheDocument()
    expect(screen.getByText(/still a draft/)).toBeInTheDocument()
    expect(frame.querySelector('main.portal')).toHaveStyle({ '--accent': '#aa3300' }) // the brand stays inside the preview
    await userEvent.selectOptions(screen.getByLabelText('See it as'), 'c2')
    await waitFor(() => expect(calls.some((c) => c.path === '/onboardings/o1/preview?contact_id=c2')).toBe(true))
  })

  test('a focus-layout preview opens on the first step still waiting, as the real portal would, with nothing to save', async () => {
    const steps = [
      step({ key: 'done1', title: 'Business details', status: 'done', can_write: false }),
      step({ key: 'todo', title: 'Upload your logo', status: 'pending', can_write: false }),
    ]
    mockFetch({ 'GET /onboardings/o1/preview': { body: { ...pv().body, layout: 'focus', status: 'active', steps } } })
    renderRoute(<OnboardingPreviewPage />, '/onboardings/:id/preview', '/onboardings/o1/preview')
    const frame = await screen.findByRole('region', { name: 'Client preview' })
    expect(await within(frame).findByRole('heading', { name: /Upload your logo/ })).toBeInTheDocument()
    expect(within(frame).queryByText(/everything we need from you/)).toBeNull()
    expect(within(frame).getByRole('note')).toHaveTextContent('You can read this step here.')
  })
})

describe('Settings', () => {
  const org = (over = {}) => ({
    body: { id: 'org-a', name: 'Acme Agency', slug: 'acme', account_type: 'reseller', linked: true, role: 'admin', brand: BRAND, logo_url: BRAND.logo_url,
      brand_name: '', email_from_name: '', reply_to_email: '', sms_from: '', email_from_preview: 'Acme Agency <hello@voicent.test>', ...over },
  })

  test('a linked org gets its logo and colours from Voicent-App, and the senders are saved', async () => {
    const { calls } = mockFetch({ 'GET /org': org(), 'PUT /org': org({ reply_to_email: 'help@acme.test' }) })
    renderRoute(<SettingsPage />, '/settings', '/settings')
    expect(await screen.findByText(/come from Voicent-App/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Logo address')).toBeNull()
    expect(screen.getByText('Clients see: Acme Agency <hello@voicent.test>')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Replies go to'), 'help@acme.test')
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    const body = calls.find((c) => c.method === 'PUT')!.body
    expect(body).toEqual({ brand_name: '', email_from_name: '', reply_to_email: 'help@acme.test', sms_from: '' }) // no brand: it isn't ours to set
  })

  test('an org with no tenant sets its own logo and colours, and problems are listed', async () => {
    const { calls } = mockFetch({
      'GET /org': org({ linked: false, logo_url: null, brand: { ...BRAND, logo_url: null, primary_color: null } }),
      'PUT /org': { status: 422, body: { detail: 'Some settings need fixing.', problems: ['Main colour: use a colour like #0b5cff.'] } },
    })
    renderRoute(<SettingsPage />, '/settings', '/settings')
    await userEvent.type(await screen.findByLabelText('Main colour'), 'blue')
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText('Main colour: use a colour like #0b5cff.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PUT')!.body.brand).toEqual({ logo_url: '', primary_color: 'blue', accent_color: '' })
  })

  test('someone who is not an admin sees the settings but cannot change them', async () => {
    mockFetch({ 'GET /org': org({ role: 'member' }) })
    renderRoute(<SettingsPage />, '/settings', '/settings')
    expect(await screen.findByText('Only an admin of Acme Agency can change these.')).toBeInTheDocument()
    expect(screen.getByLabelText('Replies go to')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save settings' })).toBeNull()
  })
})

describe('paying customers', () => {
  const client: Client = { id: 'cl1', name: 'Acme', kind: 'msp', status: 'active', notes: '', timezone: 'America/New_York', created_at: '2026-11-01T00:00:00Z', paying_since: null, outcome: null, stage: 'lead', contacts: [] }

  test('the client page marks a client as paying, after asking', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockFetch({ 'GET /clients': { body: [client] }, 'GET /onboardings': { body: [] }, 'POST /clients/cl1/paying': { body: { ...client, paying_since: '2026-11-20T00:00:00Z' } } })
    renderRoute(<ClientDetail />, '/clients/:id', '/clients/cl1')
    expect(await screen.findByText('Not paying yet (a lead)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Mark as paying' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ paying: true }))
  })

  test('a finished onboarding of a client who has not paid waits, and says so', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const ob = { id: 'o1', client_id: 'cl1', status: 'completed' } as OnboardingDetail
    const unpaid = { enabled: true, wanted: true, state: 'unpaid', workspace_id: null, attempts: 0, next_attempt_at: null, delivered_at: null, error: '', log: [], client_id: 'cl1', paying: false }
    const { calls } = mockFetch({ 'GET /onboardings/o1/provision': { body: unpaid }, 'POST /clients/cl1/paying': { body: { ...client, paying_since: 'x' } } })
    renderRoute(<VoicentPanel ob={ob} />, '/', '/')
    expect(await screen.findByText('Waiting for payment')).toBeInTheDocument()
    expect(screen.getByText(/stay a lead and nothing goes to Voicent-App/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Send to Voicent-App/ })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Mark as a paying customer' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/clients/cl1/paying')).toBe(true))
  })
})
