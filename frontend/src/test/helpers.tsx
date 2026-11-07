import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'
import type { PortalStep, PortalView } from '../api/types'
import { PortalContext, type PortalApi } from '../portal/session'

export function step(over: Partial<PortalStep> = {}): PortalStep {
  return {
    key: 'basics', type: 'form', title: 'Basics', description: '', section: '', position: 0, status: 'pending', due_at: null,
    config: { fields: [] }, assignee: null, can_write: true, response: null, files: [], comments: [], ...over,
  }
}

export function view(over: Partial<PortalView> = {}): PortalView {
  return {
    title: 'Kickoff', layout: 'checklist', status: 'active', client_name: 'Acme', contact: { id: 'c1', name: 'Pat Owner' },
    sections: [], progress: { done: 0, total: 0 }, steps: [], ...over,
  }
}

export interface Reply { status?: number; body?: unknown; headers?: Record<string, string> }
export type Handler = (url: string, init: RequestInit) => Reply

/** A stand-in for fetch: answers by "METHOD /path". Anything unexpected fails the test loudly. */
export function mockFetch(handlers: Record<string, Handler | Reply>) {
  const calls: { method: string; path: string; body: any; headers: Record<string, string> }[] = []
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? 'GET').toUpperCase()
    const path = String(url).replace(/^\/api/, '')
    calls.push({ method, path, body: init.body ? JSON.parse(String(init.body)) : undefined, headers: (init.headers ?? {}) as Record<string, string> })
    const h = handlers[`${method} ${path}`]
    if (!h) throw new Error(`Unexpected request: ${method} ${path}`)
    const r = typeof h === 'function' ? h(path, init) : h
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), { status: r.status ?? 200, headers: { 'Content-Type': 'application/json', ...r.headers } })
  })
  vi.stubGlobal('fetch', fn)
  return { fn, calls }
}

/** Components that talk to the portal get a fake session by default; pass `portal` to script its calls. */
export function renderRoute(ui: ReactElement, path: string, at: string, portal?: Partial<PortalApi>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const api: PortalApi = { status: 'ready', call: vi.fn(async () => undefined as never), ...portal }
  return render(
    <QueryClientProvider client={qc}>
      <PortalContext.Provider value={api}>
        <MemoryRouter initialEntries={[at]}>
          <Routes>
            <Route path={path} element={ui} />
          </Routes>
        </MemoryRouter>
      </PortalContext.Provider>
    </QueryClientProvider>,
  )
}
