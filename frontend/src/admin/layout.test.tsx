import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { mockFetch } from '../test/helpers'
import AdminLayout from './AdminLayout'

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ email: 'jay@x.test', signOut: vi.fn() }) }))

const shell = () => document.querySelector('.admin-shell')!

const ORG = { id: 'org-a', name: 'Acme Agency', account_type: 'reseller', role: 'admin' }
const settings = (over = {}) => ({
  body: { id: 'org-a', name: 'Acme Agency', slug: 'acme', account_type: 'reseller', linked: true, role: 'admin', logo_url: null, brand_name: '', email_from_name: '',
    reply_to_email: '', sms_from: '', email_from_preview: null, brand: { name: 'Acme Agency', logo_url: null, primary_color: '#aa3300', accent_color: null }, ...over },
})

function renderAt(path = '/', orgs = [ORG]) {
  const fetched = mockFetch({ 'GET /me': { body: { id: 'u', email: 'jay@x.test', kind: 'user', superuser: false, orgs } }, 'GET /org': settings(), 'GET /notifications': { body: { unread: 3, items: [] } } })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AdminLayout />}>
          <Route index element={<p>Home page</p>} />
          <Route path="templates" element={<p>Templates page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>
    </QueryClientProvider>,
  )
  return fetched
}

describe('the left menu', () => {
  beforeEach(() => localStorage.clear())

  test('links keep their names when collapsed, and the choice is remembered', async () => {
    renderAt()
    const toggle = await screen.findByRole('button', { name: 'Collapse the menu' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(toggle)
    expect(shell()).toHaveClass('is-collapsed')
    expect(screen.getByRole('button', { name: 'Expand the menu' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('link', { name: 'Templates' })).toHaveAttribute('title', 'Templates') // the label stays for screen readers, the title for a tooltip
    document.body.innerHTML = ''
    renderAt()
    await screen.findByRole('button', { name: 'Expand the menu' })
    expect(shell()).toHaveClass('is-collapsed')
  })

  test('the phone drawer opens, closes on Escape, and closes after picking a page', async () => {
    renderAt()
    const menu = await screen.findByRole('button', { name: 'Menu' })
    await userEvent.click(menu)
    expect(shell()).toHaveClass('is-open')
    expect(menu).toHaveAttribute('aria-expanded', 'true')
    await userEvent.keyboard('{Escape}')
    expect(shell()).not.toHaveClass('is-open')
    await userEvent.click(menu)
    await userEvent.click(screen.getByRole('button', { name: 'Close the menu' }))
    expect(shell()).not.toHaveClass('is-open')
    await userEvent.click(menu)
    await userEvent.click(screen.getByRole('link', { name: 'Templates' }))
    expect(screen.getByText('Templates page')).toBeInTheDocument()
    expect(shell()).not.toHaveClass('is-open')
  })

  test('the current page is marked', async () => {
    renderAt('/templates')
    expect(await screen.findByRole('link', { name: 'Templates' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Onboardings' })).not.toHaveAttribute('aria-current')
  })

  test("the org's brand colours the admin app and every request says which org it is for", async () => {
    const { calls } = renderAt()
    await waitFor(() => expect(shell()).toHaveStyle({ '--accent': '#aa3300' }))
    expect(screen.getAllByText('Acme Agency').length).toBeGreaterThan(0)
    expect(screen.queryByText(/Voicent/)).toBeNull()
    expect(calls.find((c) => c.path === '/org')!.headers['X-Org-Id']).toBe('org-a')
    expect(screen.queryByRole('combobox', { name: 'Organization' })).toBeNull() // only one to work in
    expect(await screen.findByRole('link', { name: 'Notifications, 3 new' })).toBeInTheDocument()
  })

  test('with several orgs (a Voicent superuser) the choice is offered and remembered', async () => {
    const other = { id: 'org-b', name: 'Voicent', account_type: 'direct', role: 'admin' }
    const { calls } = renderAt('/', [ORG, other])
    const pick = await screen.findByRole('combobox', { name: 'Organization' })
    await userEvent.selectOptions(pick, 'org-b')
    await waitFor(() => expect(calls.filter((c) => c.path === '/org').at(-1)!.headers['X-Org-Id']).toBe('org-b'))
    expect(localStorage.getItem('vo.org')).toBe('org-b')
  })
})
