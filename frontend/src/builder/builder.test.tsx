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
})

describe('OnboardingStepsPage', () => {
  const ob = { 'GET /onboardings/o1': { body: { id: 'o1', title: 'Mini: Acme', steps: [] } } }

  test('a draft saves its steps with PUT', async () => {
    const { calls } = mockFetch({
      ...ob, 'GET /templates': { body: [] },
      'GET /onboardings/o1/document': { body: { document: DOC, editable: true, locked: ['basics'] } },
      'PUT /onboardings/o1/document': { body: { document: { ...DOC, steps: [FORM] }, editable: true, locked: ['basics'], steps: [] } },
    })
    renderRoute(<OnboardingStepsPage />, '/onboardings/:id/steps', '/onboardings/o1/steps')
    expect(await screen.findByRole('button', { name: 'Remove “Basics”' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save steps' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Remove “Approve”' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save steps' }))
    expect(await screen.findByText(/Saved. The client sees these steps/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PUT')!.body).toEqual({ sections: [], steps: [FORM] })
  })

  test('after sending, steps are shown but not editable, and can still become a template', async () => {
    mockFetch({ ...ob, 'GET /templates': { body: [] }, 'GET /onboardings/o1/document': { body: { document: DOC, editable: false, locked: [] } } })
    renderRoute(<OnboardingStepsPage />, '/onboardings/:id/steps', '/onboardings/o1/steps')
    expect(await screen.findByText(/has been sent, so its steps can't change/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save steps' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save as template' })).toBeInTheDocument()
  })
})
