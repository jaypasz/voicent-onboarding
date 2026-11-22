import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, test, vi } from 'vitest'
import type { PortalStep, Team } from '../api/types'
import StepsBuilder, { type BuilderValue } from '../builder/StepsBuilder'
import { prepare, type StepDoc } from '../builder/doc'
import TaskStep from '../portal/steps/TaskStep'
import { mockFetch, renderRoute } from '../test/helpers'
import TasksPage from './TasksPage'

const step = (over: Partial<PortalStep> = {}): PortalStep => ({
  key: 'prices', type: 'task', title: 'Send your price list', description: '', section: '', position: 0, status: 'pending', due_at: null,
  config: { audience: 'client', instructions: 'Any format is fine.', checklist: ['Find it', 'Send it'] }, assignee: null, can_write: true, response: null, files: [], comments: [], ...over,
})

describe('a task for the client', () => {
  test('ticking an item saves it at once, and the saved ticks show', async () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    const { rerender } = render(<TaskStep step={step()} submit={submit} busy={false} problems={[]} />)
    expect(screen.getByText('Any format is fine.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Find it' }))
    expect(submit).toHaveBeenLastCalledWith({ checked: [0] })
    rerender(<TaskStep step={step({ status: 'in_progress', response: { checked: [0], done: false } })} submit={submit} busy={false} problems={[]} />)
    expect(screen.getByRole('checkbox', { name: 'Find it' })).toBeChecked()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Find it' }))
    expect(submit).toHaveBeenLastCalledWith({ checked: [] })
  })

  test('a task without a checklist has a button, and the note goes with it', async () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    render(<TaskStep step={step({ config: { audience: 'client' } })} submit={submit} busy={false} problems={[]} />)
    expect(screen.queryByRole('checkbox')).toBeNull()
    await userEvent.type(screen.getByLabelText('Note for us (optional)'), 'Sent by email')
    await userEvent.click(screen.getByRole('button', { name: 'Mark as done' }))
    expect(submit).toHaveBeenCalledWith({ done: true, note: 'Sent by email' })
  })

  test("someone else's task can be read but not changed", () => {
    render(<TaskStep step={step({ can_write: false })} submit={vi.fn()} busy={false} problems={[]} />)
    expect(screen.getByRole('checkbox', { name: 'Find it' })).toBeDisabled()
    expect(screen.queryByRole('button')).toBeNull()
  })

  test('what the server refused is shown', () => {
    render(<TaskStep step={step()} submit={vi.fn()} busy={false} problems={['Tick every item before marking this done.']} />)
    expect(screen.getByText('Tick every item before marking this done.')).toBeInTheDocument()
  })
})

describe('choosing who a task is for', () => {
  function Harness({ steps, locked = [] as string[], spy }: { steps: StepDoc[]; locked?: string[]; spy: (v: BuilderValue) => void }) {
    const [value, setValue] = useState<BuilderValue>({ sections: [], steps: prepare(steps) })
    return <StepsBuilder value={value} locked={locked} onChange={(v) => { setValue(v); spy(v) }} />
  }
  const TASK: StepDoc = { key: 'chase', type: 'task', title: 'Chase it', section: '', visibility: 'client', config: { audience: 'client' } }

  test('the audience decides who sees it, and a team task has no "who answers" role', async () => {
    const spy = vi.fn()
    render(<Harness steps={[TASK]} spy={spy} />)
    await userEvent.click(screen.getByRole('button', { name: /Chase it/, expanded: false }))
    expect(screen.getByLabelText('Who answers (role)')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Who does it'), 'team')
    expect((spy.mock.calls.at(-1)![0] as BuilderValue).steps[0]).toMatchObject({ visibility: 'internal', config: { audience: 'team' } })
    expect(screen.queryByLabelText('Who answers (role)')).toBeNull()
  })

  test('a task that has answers keeps its audience', async () => {
    render(<Harness steps={[TASK]} locked={['chase']} spy={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: /Chase it/, expanded: false }))
    expect(screen.getByLabelText('Who does it')).toBeDisabled()
  })

  test('the palette adds a task for the client', async () => {
    const spy = vi.fn()
    render(<Harness steps={[]} spy={spy} />)
    await userEvent.click(screen.getByRole('button', { name: /Task.*add to the end/ }))
    expect((spy.mock.calls.at(-1)![0] as BuilderValue).steps[0]).toMatchObject({ type: 'task', visibility: 'client', config: { audience: 'client' } })
  })
})

describe('the tasks page, with tasks that sit in onboardings', () => {
  const team: Team = { linked: false, in_sync: true, can_manage: true, me: 'm-jay', invites: [],
    members: [{ id: 'm-jay', email: 'jay@x.test', name: 'Jay', role: 'admin', source: 'local', is_you: true, notify_email: true }] }

  test('lists them with a link to the step, beside the other to-dos', async () => {
    mockFetch({
      'GET /clients': { body: [{ id: 'cl1', name: 'Acme', contacts: [] }] }, 'GET /team': { body: team }, 'GET /tasks?done=false': { body: [] },
      'GET /tasks/in-onboardings?done=false': { body: [{ onboarding_id: 'o1', key: 'build', title: 'Build the agent', client_id: 'cl1', status: 'pending', team_assignee_id: 'm-jay', due_at: null }] },
    })
    renderRoute(<TasksPage />, '/tasks', '/tasks')
    const link = await screen.findByRole('link', { name: 'Build the agent' })
    expect(link).toHaveAttribute('href', '/onboardings/o1#step-build')
    const row = link.closest('li')!
    expect(within(row).getByRole('link', { name: 'Acme' })).toBeInTheDocument()
    expect(within(row).getByText('Jay')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('No tasks.')).toBeInTheDocument())
  })
})
