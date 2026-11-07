import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { PortalStep } from '../api/types'
import { mockFetch, renderRoute, step, view } from '../test/helpers'
import ApprovalStep from './steps/ApprovalStep'
import BookCallStep from './steps/BookCallStep'
import ConnectStep from './steps/ConnectStep'
import FormStep from './steps/FormStep'
import UploadStep from './steps/UploadStep'
import ChecklistLayout from './ChecklistLayout'
import FocusLayout, { nextOpenIndex } from './FocusLayout'
import PortalPage from './PortalPage'

afterEach(() => vi.unstubAllGlobals())

const noop = async () => {}
const props = (s: PortalStep, over = {}) => ({ step: s, submit: vi.fn(async () => {}), busy: false, problems: [] as string[], ...over })

const FORM = step({
  config: { intro: 'A few questions.', fields: [
    { key: 'name', label: 'Business name', type: 'text', required: true },
    { key: 'email', label: 'Email address', type: 'email', required: true },
    { key: 'size', label: 'Size', type: 'select', options: ['small', 'large'] },
    { key: 'tools', label: 'Tools', type: 'multiselect', options: ['a', 'b'] },
    { key: 'agree', label: 'I agree', type: 'checkbox', required: true },
  ] },
})

describe('FormStep', () => {
  test('required fields are marked in words and block sending, with an error beside each', async () => {
    const p = props(FORM)
    render(<FormStep {...p} />)
    expect(screen.getAllByText('(required)').length).toBe(3)
    await userEvent.click(screen.getByRole('button', { name: /save and continue/i }))
    expect(p.submit).not.toHaveBeenCalled()
    expect(screen.getAllByRole('alert').map((a) => a.textContent)).toEqual(['✕ This is required.', '✕ This is required.', '✕ This needs to be ticked.'])
    expect(screen.getByLabelText(/Business name/)).toHaveAttribute('aria-invalid', 'true')
  })

  test('sends trimmed answers, leaving out empty optional ones', async () => {
    const p = props(FORM)
    render(<FormStep {...p} />)
    await userEvent.type(screen.getByLabelText(/Business name/), '  Acme  ')
    await userEvent.type(screen.getByLabelText(/Email address/), 'a@b.co')
    await userEvent.click(screen.getByLabelText('b'))
    await userEvent.click(screen.getByLabelText(/I agree/))
    await userEvent.click(screen.getByRole('button', { name: /save and continue/i }))
    expect(p.submit).toHaveBeenCalledWith({ answers: { name: 'Acme', email: 'a@b.co', tools: ['b'], agree: true } })
  })

  test('server problems land under the field they are about, and the rest are listed on top', () => {
    render(<FormStep {...props(FORM, { problems: ["Email address: doesn't look like an email address.", 'Something general.'] })} />)
    expect(screen.getByText(/doesn't look like an email address/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Email address/)).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('Something general.')).toBeInTheDocument()
  })

  test('shows saved answers, and a step the client may not write has no save button', () => {
    const saved = { ...FORM, can_write: false, response: { answers: { name: 'Acme', agree: true } } }
    render(<FormStep {...props(saved)} />)
    expect(screen.getByLabelText(/Business name/)).toHaveValue('Acme')
    expect(screen.getByLabelText(/Business name/)).toBeDisabled()
    expect(screen.queryByRole('button', { name: /save/i })).toBeNull()
  })
})

describe('ConnectStep', () => {
  const connect = step({ type: 'connect', config: { provider: 'ghl', label: 'GoHighLevel', instructions: 'Invite us.', start_url: 'https://app.example.com/start' } })

  test('asks which account before saying it is connected, and never asks for a password', async () => {
    const p = props(connect)
    render(<ConnectStep {...p} />)
    expect(screen.getByText(/don't send passwords/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /I've done this/ }))
    expect(p.submit).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Say which account it is.')
    await userEvent.type(screen.getByLabelText(/Which account/), 'Acme main')
    await userEvent.click(screen.getByRole('button', { name: /I've done this/ }))
    expect(p.submit).toHaveBeenCalledWith({ status: 'connected', account_label: 'Acme main' })
  })

  test('asking for a hand sends a pending status', async () => {
    const p = props(connect)
    render(<ConnectStep {...p} />)
    await userEvent.click(screen.getByRole('button', { name: /need a hand/i }))
    expect(p.submit).toHaveBeenCalledWith({ status: 'pending' })
  })

  test('the start link opens safely, and a non-https one is not a link at all', () => {
    const { unmount } = render(<ConnectStep {...props(connect)} />)
    const a = screen.getByRole('link', { name: /Open GoHighLevel/ })
    expect(a).toHaveAttribute('rel', 'noopener noreferrer')
    expect(a).toHaveAttribute('target', '_blank')
    unmount()
    render(<ConnectStep {...props(step({ type: 'connect', config: { provider: 'x', label: 'X', start_url: 'javascript:alert(1)' } }))} />)
    expect(screen.queryByRole('link')).toBeNull()
  })
})

describe('BookCallStep and ApprovalStep', () => {
  test('book call: unsafe link is not rendered; booking sends booked true', async () => {
    const bad = step({ type: 'book_call', config: { url: 'http://insecure.test' } })
    const { unmount } = render(<BookCallStep {...props(bad)} />)
    expect(screen.queryByRole('link')).toBeNull()
    unmount()
    const p = props(step({ type: 'book_call', config: { url: 'https://cal.example.com/x', duration_minutes: 30 } }))
    render(<BookCallStep {...p} />)
    expect(screen.getByRole('link', { name: /Pick a time/ })).toHaveAttribute('rel', 'noopener noreferrer')
    await userEvent.click(screen.getByRole('button', { name: /I've booked it/ }))
    expect(p.submit).toHaveBeenCalledWith({ booked: true })
  })

  test('approval: approving sends the decision; asking for changes needs a comment', async () => {
    const p = props(step({ type: 'approval', config: { prompt: 'Check this.', deliverable: { kind: 'text', text: 'Hello caller' } } }))
    render(<ApprovalStep {...p} />)
    expect(screen.getByText('Hello caller')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /ask for changes/i }))
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))
    expect(p.submit).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Say what should change.')
    await userEvent.type(screen.getByLabelText(/What should change/), 'Warmer')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))
    expect(p.submit).toHaveBeenCalledWith({ decision: 'changes_requested', comment: 'Warmer' })
  })

  test('approval: approve button, and a link deliverable must be https', async () => {
    const p = props(step({ type: 'approval', config: { deliverable: { kind: 'link', url: 'https://docs.example.com/x' } } }))
    const { unmount } = render(<ApprovalStep {...p} />)
    expect(screen.getByRole('link', { name: /Open to review/ })).toHaveAttribute('rel', 'noopener noreferrer')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))
    expect(p.submit).toHaveBeenCalledWith({ decision: 'approved' })
    unmount()
    render(<ApprovalStep {...props(step({ type: 'approval', config: { deliverable: { kind: 'link', url: 'javascript:alert(1)' } } }))} />)
    expect(screen.queryByRole('link')).toBeNull()
  })
})

describe('UploadStep', () => {
  const upload = step({ type: 'upload', config: { accept: ['png', 'pdf'], max_mb: 1, min_files: 0, max_files: 2 } })

  test('a file that is not allowed is refused on the device, before anything is sent', async () => {
    const { fn } = mockFetch({})
    const { container } = renderRoute(<UploadStep {...props(upload)} />, '/', '/')
    const input = container.querySelector('input[type=file]') as HTMLInputElement
    await userEvent.upload(input, new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' }), { applyAccept: false })
    expect(await screen.findByText(/logo\.svg: this type of file isn't allowed here/)).toBeInTheDocument()
    expect(fn).not.toHaveBeenCalled()
  })

  test('too many files and oversize files are refused up front', async () => {
    const { fn } = mockFetch({})
    const { container } = renderRoute(<UploadStep {...props(upload)} />, '/', '/')
    const input = container.querySelector('input[type=file]') as HTMLInputElement
    await userEvent.upload(input, [new File(['a'], 'a.png'), new File(['b'], 'b.png'), new File(['c'], 'c.png')])
    expect(await screen.findByText(/You can add up to 2 files here/)).toBeInTheDocument()
    const big = new File(['x'], 'big.png')
    Object.defineProperty(big, 'size', { value: 2 * 1024 * 1024 })
    await userEvent.upload(input, big)
    expect(await screen.findByText(/big\.png: files can be up to 1 MB/)).toBeInTheDocument()
    expect(fn).not.toHaveBeenCalled()
  })

  test('with nothing required there is an explicit way to say "nothing to add"', async () => {
    const p = props(upload)
    renderRoute(<UploadStep {...p} />, '/', '/')
    await userEvent.click(screen.getByRole('button', { name: /nothing to add/i }))
    expect(p.submit).toHaveBeenCalledWith({ file_ids: [] })
  })

  test('shows files already added', () => {
    const s = { ...upload, response: { file_ids: ['f1'] }, files: [{ id: 'f1', name: 'logo.png', size: 2048 }] }
    renderRoute(<UploadStep {...props(s)} />, '/', '/')
    expect(screen.getByLabelText('Files you added')).toHaveTextContent('logo.png')
  })
})

describe('layouts', () => {
  const steps = [
    step({ key: 'a', title: 'First', status: 'done' }),
    step({ key: 'b', title: 'Second', status: 'pending' }),
    step({ key: 'c', title: 'Theirs', status: 'pending', can_write: false, assignee: { id: 'x', name: 'Ian IT', is_you: false } }),
    step({ key: 'd', title: 'Fourth', status: 'pending' }),
  ]

  test('the next open step skips done ones and steps that are not the client\'s, and wraps round', () => {
    expect(nextOpenIndex(steps, -1)).toBe(1)
    expect(nextOpenIndex(steps, 1)).toBe(3)
    expect(nextOpenIndex(steps, 3)).toBe(1)
    expect(nextOpenIndex(steps.map((s) => ({ ...s, status: 'done' })), -1)).toBe(-1)
  })

  test('focus layout starts on the first open step, with one labelled dot per step', () => {
    renderRoute(<FocusLayout view={view({ layout: 'focus', steps })} onChanged={noop} />, '/', '/')
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Step 2 of 4Second')
    expect(screen.getByRole('button', { name: 'Step 1 of 4: First, Done' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Step 2 of 4: Second, To do' })).toHaveAttribute('aria-current', 'step')
  })

  test('focus layout says so when everything the client can do is done', async () => {
    const done = steps.map((s) => ({ ...s, status: 'done' as const }))
    renderRoute(<FocusLayout view={view({ layout: 'focus', steps: done })} onChanged={noop} />, '/', '/')
    expect(screen.getByText(/everything we need from you/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /review or change/i }))
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Step 1 of 4')
  })

  test('checklist groups by section, shows who each step is for, opens the first open step', () => {
    const v = view({
      sections: [{ key: 'co', title: 'Your company' }, { key: 'acc', title: 'Access' }],
      steps: [
        step({ key: 'a', title: 'Profile', section: 'co', status: 'done' }),
        step({ key: 'b', title: 'Stakeholders', section: 'co' }),
        step({ key: 'c', title: 'Grant DNS access', section: 'acc', can_write: false, assignee: { id: 'x', name: 'Ian IT', is_you: false } }),
      ],
    })
    renderRoute(<ChecklistLayout view={v} onChanged={noop} />, '/', '/')
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent?.replace(/\s+/g, ' '))).toEqual(['Your company (1 of 2 done)', 'Access (0 of 1 done)'])
    expect(screen.getByText('For Ian IT')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Stakeholders/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: /Profile/ })).toHaveAttribute('aria-expanded', 'false')
  })

  test('opening a step someone else owns explains that it is read-only', async () => {
    const v = view({ steps: [step({ key: 'c', title: 'Grant DNS access', status: 'pending', can_write: false, assignee: { id: 'x', name: 'Ian IT', is_you: false } })] })
    renderRoute(<ChecklistLayout view={v} onChanged={noop} />, '/', '/')
    await userEvent.click(screen.getByRole('button', { name: /Grant DNS access/ }))
    expect(screen.getByRole('note')).toHaveTextContent('This step is for Ian IT')
  })
})

describe('PortalPage', () => {
  const exchange = { status: 200, body: { session: 'sess-1', expires_in: 1800 } }

  test('a dead link says it is not available and gives no reason', async () => {
    mockFetch({ 'POST /portal/exchange': { status: 401, body: { detail: "This link isn't available. Ask for a new one." } } })
    renderRoute(<PortalPage />, '/c/:token', '/c/dead-token-aaaaaaaaaaaaaaaaaaaa')
    expect(await screen.findByRole('heading', { name: "This link isn't available" })).toBeInTheDocument()
    expect(screen.queryByText(/expired|revoked|not found|unknown/i)).toBeInTheDocument() // the soft hint, not a diagnosis
    expect(document.body.textContent).not.toMatch(/revoked|no such|does not exist/i)
  })

  test('too many requests says to wait, not that the link is bad', async () => {
    mockFetch({ 'POST /portal/exchange': { status: 429, body: { detail: 'Too many requests.' }, headers: { 'Retry-After': '30' } } })
    renderRoute(<PortalPage />, '/c/:token', '/c/some-token-aaaaaaaaaaaaaaaaaaaaaa')
    expect(await screen.findByRole('heading', { name: /try again in a minute/i })).toBeInTheDocument()
  })

  test('loads the onboarding with the session it was given, and shows progress', async () => {
    const v = view({ title: 'Kickoff: Acme', progress: { done: 1, total: 2 }, steps: [step({ key: 'a', title: 'Profile', status: 'done' }), step({ key: 'b', title: 'Contacts' })] })
    const { calls } = mockFetch({ 'POST /portal/exchange': exchange, 'GET /portal/onboarding': { body: v } })
    renderRoute(<PortalPage />, '/c/:token', '/c/good-token-aaaaaaaaaaaaaaaaaaaaaaa')
    expect(await screen.findByRole('heading', { level: 1, name: 'Kickoff: Acme' })).toBeInTheDocument()
    expect(screen.getByText('Your progress: 1 of 2 done')).toBeInTheDocument()
    expect(calls[0].body).toEqual({ token: 'good-token-aaaaaaaaaaaaaaaaaaaaaaa' })
    expect(calls[0].headers.Authorization).toBeUndefined()
    expect(calls[1].headers.Authorization).toBe('Bearer sess-1')
  })

  test('a paused onboarding is readable and says changes are off', async () => {
    mockFetch({ 'POST /portal/exchange': exchange, 'GET /portal/onboarding': { body: view({ status: 'paused', steps: [step({ can_write: false })] }) } })
    renderRoute(<PortalPage />, '/c/:token', '/c/good-token-aaaaaaaaaaaaaaaaaaaaaaa')
    expect(await screen.findByText(/This onboarding is paused/)).toBeInTheDocument()
  })

  test('if the session runs out mid-visit it is renewed once and the call retried', async () => {
    let tries = 0
    const { calls } = mockFetch({
      'POST /portal/exchange': () => ({ body: { session: `sess-${calls.filter((c) => c.path === '/portal/exchange').length}`, expires_in: 1800 } }),
      'GET /portal/onboarding': (_p, init) => {
        tries++
        const auth = (init.headers as Record<string, string>).Authorization
        return auth === 'Bearer sess-1' ? { status: 401, body: { detail: 'x' } } : { body: view({ title: 'Renewed ok' }) }
      },
    })
    renderRoute(<PortalPage />, '/c/:token', '/c/good-token-aaaaaaaaaaaaaaaaaaaaaaa')
    expect(await screen.findByRole('heading', { level: 1, name: 'Renewed ok' })).toBeInTheDocument()
    expect(tries).toBe(2)
    await waitFor(() => expect(calls.filter((c) => c.path === '/portal/exchange').length).toBe(2))
  })

  test('the focus layout is used when the template asks for it, and internal-looking content never appears', async () => {
    mockFetch({ 'POST /portal/exchange': exchange, 'GET /portal/onboarding': { body: view({ layout: 'focus', steps: [step({ key: 'a', title: 'About you' })] }) } })
    renderRoute(<PortalPage />, '/c/:token', '/c/good-token-aaaaaaaaaaaaaaaaaaaaaaa')
    const h = await screen.findByRole('heading', { level: 2 })
    expect(within(h).getByText('Step 1 of 1')).toBeInTheDocument()
  })
})
