import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, test, vi } from 'vitest'
import NewOnboardingPage from '../admin/NewOnboardingPage'
import OnboardingStepsPage from '../admin/OnboardingStepsPage'
import { mockFetch, renderRoute } from '../test/helpers'
import StepsBuilder, { type BuilderValue } from './StepsBuilder'
import { clean, prepare, toKey, toSlug, uniqueKey, type StepDoc, type TemplateDoc } from './doc'

const FORM: StepDoc = { key: 'basics', type: 'form', title: 'Basics', section: '', config: { fields: [{ key: 'name', label: 'Name', type: 'text', required: true }] } }
const APPROVE: StepDoc = { key: 'approve', type: 'approval', title: 'Approve', section: '', config: { deliverable: { kind: 'text', text: 'Hi' } } }
const DOC: TemplateDoc = { name: 'Mini', slug: 'mini', version: 1, layout: 'checklist', sections: [], steps: [FORM, APPROVE] }

function Harness({ steps = [FORM, APPROVE], locked = [] as string[], spy = (_v: BuilderValue) => {} }) {
  const [value, setValue] = useState<BuilderValue>({ sections: [], steps: prepare(steps) })
  return <StepsBuilder value={value} locked={locked} onChange={(v) => { setValue(v); spy(v) }} />
}

const titles = () => within(screen.getByRole('list', { name: 'Steps, in order' })).getAllByRole('button', { name: /settings|Basics|Approve|Form|File upload|Your logo|Untitled/ })
  .filter((b) => b.classList.contains('step-item-title')).map((b) => b.querySelector('strong')!.textContent)

describe('document helpers', () => {
  test('keys and slugs are what the server accepts', () => {
    expect(toKey('Your Logo & Brand!')).toBe('your_logo_brand')
    expect(toKey('2024 plans')).toBe('step_2024_plans')
    expect(toKey('')).toBe('step')
    expect(toSlug('MSP — Custom')).toBe('msp-custom')
    expect(uniqueKey('form', ['form', 'form_2'])).toBe('form_3')
  })

  test('clean strips the builder bookkeeping, also inside form questions', () => {
    const out = clean(prepare([FORM]))
    expect(JSON.stringify(out)).not.toMatch(/_uid|_fresh/)
    expect(out[0]).toEqual(FORM)
  })
})

describe('StepsBuilder', () => {
  test('a step from the menu is added at the end and opened, and its key follows its title', async () => {
    const spy = vi.fn()
    render(<Harness spy={spy} />)
    await userEvent.click(screen.getByRole('button', { name: /File upload.*add to the end/ }))
    expect(titles()).toEqual(['Basics', 'Approve', 'File upload'])
    const title = screen.getByLabelText('Title')
    await userEvent.clear(title)
    await userEvent.type(title, 'Your logo')
    const last = spy.mock.calls.at(-1)![0] as BuilderValue
    expect(last.steps[2]).toMatchObject({ key: 'your_logo', type: 'upload', visibility: 'client', config: { accept: ['pdf', 'png', 'jpg'] } })
    expect(last.steps[0].key).toBe('basics') // existing steps keep their keys
  })

  test('steps move with the buttons, and the move is announced', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Move “Basics” down' }))
    expect(titles()).toEqual(['Approve', 'Basics'])
    expect(screen.getByText('Moved “Basics” to position 2.')).toHaveAttribute('role', 'status')
    expect(screen.getByRole('button', { name: 'Move “Approve” up' })).toBeDisabled()
  })

  test('a step with answers cannot be removed, and renaming it keeps its key', async () => {
    const spy = vi.fn()
    render(<Harness locked={['basics']} spy={spy} />)
    expect(screen.getByRole('button', { name: 'Remove “Basics”' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: /Basics/, expanded: false }))
    await userEvent.type(screen.getByLabelText('Title'), ' about you')
    expect((spy.mock.calls.at(-1)![0] as BuilderValue).steps[0].key).toBe('basics')
    await userEvent.click(screen.getByRole('button', { name: 'Remove “Approve”' }))
    expect(titles()).toEqual(['Basics about you'])
  })

  test('with a form open, the right-hand menu adds questions to it', async () => {
    const spy = vi.fn()
    render(<Harness spy={spy} />)
    expect(screen.queryByRole('heading', { name: /Add a question/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Basics/, expanded: false }))
    expect(screen.getByRole('heading', { name: 'Add a question to “Basics”' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Pick one' }))
    const fields = (spy.mock.calls.at(-1)![0] as BuilderValue).steps[0].config.fields
    expect(fields).toHaveLength(2)
    expect(fields[1]).toMatchObject({ type: 'select', options: ['Option 1', 'Option 2'], key: 'new_question' })
    expect(screen.getByText('Question 2')).toBeInTheDocument()
  })

  test('the internal checklist keeps a new line and spaces while typing, and the document gets the items', async () => {
    const spy = vi.fn()
    const TASK: StepDoc = { key: 'build', type: 'internal_task', title: 'Build', section: '', visibility: 'internal', config: { checklist: ['Create it'] } }
    render(<Harness steps={[TASK]} spy={spy} />)
    await userEvent.click(screen.getByRole('button', { name: /Build/, expanded: false }))
    const box = screen.getByLabelText('Checklist, one item per line')
    await userEvent.type(box, '{Enter}Test it on a call')
    expect(box).toHaveValue('Create it\nTest it on a call')
    expect((spy.mock.calls.at(-1)![0] as BuilderValue).steps[0].config.checklist).toEqual(['Create it', 'Test it on a call'])
  })

  test('removing a section moves its steps out of it', async () => {
    const spy = vi.fn()
    render(<Harness spy={spy} />)
    await userEvent.click(screen.getByText('Sections'))
    await userEvent.type(screen.getByLabelText('New section'), 'Brand{Enter}')
    await userEvent.click(screen.getByRole('button', { name: /Basics/, expanded: false }))
    await userEvent.selectOptions(screen.getByLabelText('Section'), 'brand')
    expect((spy.mock.calls.at(-1)![0] as BuilderValue).steps[0].section).toBe('brand')
    await userEvent.click(screen.getByRole('button', { name: 'Remove section Brand' }))
    const last = spy.mock.calls.at(-1)![0] as BuilderValue
    expect(last.sections).toEqual([])
    expect(last.steps[0].section).toBe('')
  })
})

describe('NewOnboardingPage', () => {
  const base = {
    'GET /clients': { body: [{ id: 'cl1', name: 'Acme', status: 'active', contacts: [] }] },
    'GET /templates': { body: [{ id: 't1', name: 'Mini', slug: 'mini', current_version: 1, archived: false }] },
    'GET /templates/t1': { body: { id: 't1', name: 'Mini', slug: 'mini', current_version: 1, archived: false, document: DOC, versions: [1] } },
    'GET /templates?include_archived=true': { body: [{ id: 't1', name: 'Mini', slug: 'mini', current_version: 1, archived: false },
      { id: 't0', name: 'Old mini', slug: 'old-mini', current_version: 2, archived: true }] },
  }

  test('the template is used as it is unless customized', async () => {
    const { calls } = mockFetch({ ...base, 'POST /onboardings': { status: 201, body: { id: 'o1', steps: [] } }, 'GET /onboardings/o1': { body: {} } })
    renderRoute(<NewOnboardingPage />, '/new', '/new')
    await screen.findByRole('option', { name: 'Acme' })
    await screen.findByRole('option', { name: 'Mini (v1)' })
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'cl1')
    await userEvent.selectOptions(screen.getByLabelText('Template'), 't1')
    expect(await screen.findByText('Approve')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create draft' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/onboardings')).toBe(true))
    expect(calls.find((c) => c.path === '/onboardings')!.body).toEqual({ client_id: 'cl1', template_id: 't1' })
  })

  test('a customized copy goes with the request, clean, and Enter in a builder field does not submit', async () => {
    const { calls } = mockFetch({ ...base, 'POST /onboardings': { status: 201, body: { id: 'o1', steps: [] } } })
    renderRoute(<NewOnboardingPage />, '/new', '/new')
    await screen.findByRole('option', { name: 'Acme' })
    await screen.findByRole('option', { name: 'Mini (v1)' })
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'cl1')
    await userEvent.selectOptions(screen.getByLabelText('Template'), 't1')
    await userEvent.click(await screen.findByLabelText('Customize the steps for this client'))
    await userEvent.click(screen.getByRole('button', { name: /File upload.*add to the end/ }))
    await userEvent.type(screen.getByLabelText('Title'), ' here{Enter}')
    expect(calls.some((c) => c.path === '/onboardings')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Create draft' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/onboardings')).toBe(true))
    const body = calls.find((c) => c.path === '/onboardings')!.body
    expect(body.steps.map((s: StepDoc) => s.key)).toEqual(['basics', 'approve', 'file_upload_here'])
    expect(JSON.stringify(body)).not.toMatch(/_uid|_fresh/)
  })

  test('save as template refuses a name another template already has', async () => {
    mockFetch(base)
    renderRoute(<NewOnboardingPage />, '/new', '/new')
    await screen.findByRole('option', { name: 'Mini (v1)' })
    await userEvent.selectOptions(screen.getByLabelText('Template'), 't1')
    await userEvent.click(await screen.findByLabelText('Customize the steps for this client'))
    await userEvent.type(screen.getByLabelText('Template name'), 'Mini')
    expect(screen.getByText('A template with this name already exists. Choose another name.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save as template' })).toBeDisabled()
  })

  test("save as template refuses an archived template's name too, and asks the server for a new template only", async () => {
    const { calls } = mockFetch({ ...base, 'POST /templates?new=true': { status: 201, body: { id: 't2', name: 'Plumbers', slug: 'plumbers', current_version: 1, archived: false, document: DOC, versions: [1] } } })
    renderRoute(<NewOnboardingPage />, '/new', '/new')
    await screen.findByRole('option', { name: 'Mini (v1)' })
    await userEvent.selectOptions(screen.getByLabelText('Template'), 't1')
    await userEvent.click(await screen.findByLabelText('Customize the steps for this client'))
    await userEvent.type(screen.getByLabelText('Template name'), 'Old mini')
    expect(await screen.findByText('A template with this name already exists. Choose another name.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save as template' })).toBeDisabled()
    await userEvent.clear(screen.getByLabelText('Template name'))
    await userEvent.type(screen.getByLabelText('Template name'), 'Plumbers')
    await userEvent.click(screen.getByRole('button', { name: 'Save as template' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/templates?new=true')).toBe(true))
    expect(calls.some((c) => c.method === 'POST' && c.path === '/templates')).toBe(false)
  })
})

describe('OnboardingStepsPage', () => {
  const ob = { 'GET /onboardings/o1': { body: { id: 'o1', title: 'Mini: Acme', steps: [] } } }

  test('a draft saves its steps with PUT', async () => {
    const { calls } = mockFetch({
      ...ob, 'GET /templates': { body: [] },
      'GET /onboardings/o1/document': { body: { document: DOC, editable: true, sent: false, etag: 'e1', client_notice_pending: false, locked: ['basics'] } },
      'PUT /onboardings/o1/document': { body: { document: { ...DOC, steps: [FORM] }, editable: true, sent: false, etag: 'e2', client_notice_pending: false, locked: ['basics'], steps: [] } },
    })
    renderRoute(<OnboardingStepsPage />, '/onboardings/:id/steps', '/onboardings/o1/steps')
    expect(await screen.findByRole('button', { name: 'Remove “Basics”' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save steps' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Remove “Approve”' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save steps' }))
    expect(await screen.findByText(/Saved. The client sees these steps/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PUT')!.body).toEqual({ sections: [], steps: [FORM], etag: 'e1' })
  })

  test('after sending, steps stay editable: a warning, a confirmation, and the etag goes back', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockFetch({
      ...ob, 'GET /templates': { body: [] },
      'GET /onboardings/o1/document': { body: { document: DOC, editable: true, sent: true, etag: 'e1', client_notice_pending: false, locked: [] } },
      'PUT /onboardings/o1/document': { body: { document: { ...DOC, steps: [FORM] }, editable: true, sent: true, etag: 'e2', client_notice_pending: true, locked: [], steps: [] } },
    })
    renderRoute(<OnboardingStepsPage />, '/onboardings/:id/steps', '/onboardings/o1/steps')
    expect(await screen.findByText(/has been sent, so the client sees saved changes straight away/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove “Approve”' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Saved. The client sees these changes now.')).toBeInTheDocument()
    expect(window.confirm).toHaveBeenCalled()
    expect(calls.find((c) => c.method === 'PUT')!.body).toMatchObject({ etag: 'e1', notify_client: true })
    expect(await screen.findByText(/The client will be told about your changes in a few minutes/)).toBeInTheDocument()
  })

  test('unticking "tell the client" saves a silent change', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockFetch({
      ...ob, 'GET /templates': { body: [] },
      'GET /onboardings/o1/document': { body: { document: DOC, editable: true, sent: true, etag: 'e1', client_notice_pending: false, locked: [] } },
      'PUT /onboardings/o1/document': { body: { document: { ...DOC, steps: [FORM] }, editable: true, sent: true, etag: 'e2', client_notice_pending: false, locked: [], steps: [] } },
    })
    renderRoute(<OnboardingStepsPage />, '/onboardings/:id/steps', '/onboardings/o1/steps')
    await userEvent.click(await screen.findByRole('button', { name: 'Remove “Approve”' }))
    await userEvent.click(screen.getByLabelText(/Tell the client about these changes/))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('Saved. The client sees these changes now.')
    expect(calls.find((c) => c.method === 'PUT')!.body.notify_client).toBe(false)
    expect(screen.queryByText(/The client will be told/)).not.toBeInTheDocument()
  })

  test('declining the confirmation saves nothing', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { calls } = mockFetch({ ...ob, 'GET /templates': { body: [] }, 'GET /onboardings/o1/document': { body: { document: DOC, editable: true, sent: true, etag: 'e1', client_notice_pending: false, locked: [] } } })
    renderRoute(<OnboardingStepsPage />, '/onboardings/:id/steps', '/onboardings/o1/steps')
    await userEvent.click(await screen.findByRole('button', { name: 'Remove “Approve”' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  })

  test('a stale save offers to reload the latest steps', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let fresh = false
    mockFetch({
      ...ob, 'GET /templates': { body: [] },
      'GET /onboardings/o1/document': () => ({ body: { document: fresh ? { ...DOC, steps: [FORM] } : DOC, editable: true, sent: true, etag: fresh ? 'e2' : 'e1', client_notice_pending: false, locked: [] } }),
      'PUT /onboardings/o1/document': { status: 409, body: { detail: 'These steps were changed by someone else after you opened them. Reload to see their changes, then make yours again.' } },
    })
    renderRoute(<OnboardingStepsPage />, '/onboardings/:id/steps', '/onboardings/o1/steps')
    await userEvent.click(await screen.findByRole('button', { name: 'Remove “Approve”' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText(/changed by someone else/)).toBeInTheDocument()
    fresh = true
    await userEvent.click(screen.getByRole('button', { name: 'Reload the latest steps' }))
    await waitFor(() => expect(screen.queryByText(/changed by someone else/)).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Remove “Approve”' })).not.toBeInTheDocument()
  })

  test('an archived onboarding shows its steps but cannot change them, and can still become a template', async () => {
    mockFetch({ ...ob, 'GET /templates': { body: [] }, 'GET /onboardings/o1/document': { body: { document: DOC, editable: false, sent: true, etag: 'e1', client_notice_pending: false, locked: [] } } })
    renderRoute(<OnboardingStepsPage />, '/onboardings/:id/steps', '/onboardings/o1/steps')
    expect(await screen.findByText(/is archived, so its steps can't change/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save as template' })).toBeInTheDocument()
  })
})
