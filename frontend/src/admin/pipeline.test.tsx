import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { Client, Task, Team } from '../api/types'
import { mockFetch, renderRoute } from '../test/helpers'
import ClientDetail from './ClientDetail'
import ClientsPage from './ClientsPage'
import TasksPage from './TasksPage'

afterEach(() => vi.restoreAllMocks())

const client = (over: Partial<Client> = {}): Client => ({
  id: 'cl1', name: 'Acme', kind: 'trades', status: 'active', notes: '', timezone: 'America/New_York', created_at: '2026-11-01T00:00:00Z',
  paying_since: null, outcome: null, stage: 'lead', contacts: [], ...over,
})
const team: Team = {
  linked: false, in_sync: true, can_manage: true, me: 'm-jay', invites: [],
  members: [{ id: 'm-jay', email: 'jay@x.test', name: 'Jay', role: 'admin', source: 'local', is_you: true, notify_email: true }],
}
const task = (over: Partial<Task> = {}): Task => ({ id: 't1', client_id: 'cl1', onboarding_id: null, title: 'Call Pat', assignee_id: null, due_on: null, done_at: null, created_at: '2026-11-20T00:00:00Z', ...over })

describe('the client list by stage', () => {
  const all = [client({ id: 'a', name: 'Anna', stage: 'lead' }), client({ id: 'b', name: 'Bo', stage: 'onboarding' }), client({ id: 'c', name: 'Cy', stage: 'won' }), client({ id: 'd', name: 'Di', stage: 'stalled', outcome: 'stalled' })]

  test('every client shows its stage as a word, with a count per stage, and the filter narrows the list', async () => {
    mockFetch({ 'GET /clients': { body: all } })
    renderRoute(<ClientsPage />, '/clients', '/clients')
    expect(await screen.findByText('Anna')).toBeInTheDocument()
    const filter = screen.getByRole('group', { name: 'Show clients by stage' })
    expect(within(filter).getByRole('button', { name: 'All (4)' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(filter).getByRole('button', { name: 'Lost (0)' })).toBeInTheDocument()
    await userEvent.click(within(filter).getByRole('button', { name: 'Stalled (1)' }))
    expect(screen.getByText('Di')).toBeInTheDocument()
    expect(screen.queryByText('Anna')).toBeNull()
    await userEvent.click(within(filter).getByRole('button', { name: 'Lost (0)' }))
    expect(screen.getByText('No clients are lost.')).toBeInTheDocument()
  })
})

describe('a client page', () => {
  test('marks a prospect lost, then reopens them', async () => {
    let current = client()
    const { calls } = mockFetch({
      'GET /clients': () => ({ body: [current] }), 'GET /onboardings': { body: [] }, 'GET /team': { body: team }, 'GET /tasks?client_id=cl1': { body: [] },
      'POST /clients/cl1/outcome': (_p, init) => { const o = JSON.parse(String(init.body)).outcome; current = client({ outcome: o, stage: o ?? 'lead' }); return { body: current } },
    })
    renderRoute(<ClientDetail />, '/clients/:id', '/clients/cl1')
    await userEvent.click(await screen.findByRole('button', { name: 'Mark lost' }))
    expect(await screen.findByRole('button', { name: 'Reopen' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/clients/cl1/outcome')!.body).toEqual({ outcome: 'lost' })
    expect(screen.queryByRole('button', { name: 'Mark stalled' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Reopen' }))
    expect(await screen.findByRole('button', { name: 'Mark lost' })).toBeInTheDocument()
  })

  test('a paying client is won and offers no lost or stalled buttons', async () => {
    mockFetch({ 'GET /clients': { body: [client({ stage: 'won', paying_since: '2026-11-10T00:00:00Z' })] }, 'GET /onboardings': { body: [] }, 'GET /team': { body: team }, 'GET /tasks?client_id=cl1': { body: [] } })
    renderRoute(<ClientDetail />, '/clients/:id', '/clients/cl1')
    expect(await screen.findByLabelText('Stage')).toHaveTextContent('Won')
    expect(screen.queryByRole('button', { name: 'Mark lost' })).toBeNull()
  })

  test('adds a task for this client and ticks one off', async () => {
    let tasks = [task()]
    const { calls } = mockFetch({
      'GET /clients': { body: [client()] }, 'GET /onboardings': { body: [] }, 'GET /team': { body: team },
      'GET /tasks?client_id=cl1': () => ({ body: tasks }),
      'POST /tasks': (_p, init) => { const b = JSON.parse(String(init.body)); tasks = [...tasks, task({ id: 't2', title: b.title, due_on: b.due_on })]; return { status: 201, body: tasks[1] } },
      'PATCH /tasks/t1': () => { tasks = [task({ done_at: '2026-11-21T00:00:00Z' })]; return { body: tasks[0] } },
    })
    renderRoute(<ClientDetail />, '/clients/:id', '/clients/cl1')
    await userEvent.type(await screen.findByLabelText('New task'), 'Send contract')
    await userEvent.click(screen.getByRole('button', { name: 'Add task' }))
    expect(await screen.findByText('Send contract')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.path === '/tasks')!.body).toEqual({ client_id: 'cl1', title: 'Send contract', due_on: null, assignee_id: null })
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ done: true }))
  })
})

describe('the tasks page', () => {
  test('lists open tasks with their client, and "only mine" asks for just my own', async () => {
    const { calls } = mockFetch({
      'GET /clients': { body: [client()] }, 'GET /team': { body: team },
      'GET /tasks?done=false': { body: [task({ due_on: '2020-01-01' })] },
      'GET /tasks?assignee_id=m-jay&done=false': { body: [] },
    })
    renderRoute(<TasksPage />, '/tasks', '/tasks')
    expect(await screen.findByText('Call Pat')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Acme' })).toHaveAttribute('href', '/clients/cl1')
    expect(screen.getByText(/Overdue:/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Only mine'))
    await waitFor(() => expect(calls.some((c) => c.path === '/tasks?assignee_id=m-jay&done=false')).toBe(true))
    expect(await screen.findByText('No tasks.')).toBeInTheDocument()
  })
})
