import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import AdminLayout from './AdminLayout'

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ email: 'jay@x.test', signOut: vi.fn() }) }))

const shell = () => document.querySelector('.admin-shell')!

function renderAt(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AdminLayout />}>
          <Route index element={<p>Home page</p>} />
          <Route path="templates" element={<p>Templates page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('the left menu', () => {
  beforeEach(() => localStorage.clear())

  test('links keep their names when collapsed, and the choice is remembered', async () => {
    const { unmount } = renderAt()
    const toggle = screen.getByRole('button', { name: 'Collapse the menu' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(toggle)
    expect(shell()).toHaveClass('is-collapsed')
    expect(screen.getByRole('button', { name: 'Expand the menu' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('link', { name: 'Templates' })).toHaveAttribute('title', 'Templates') // the label stays for screen readers, the title for a tooltip
    unmount()
    renderAt()
    expect(shell()).toHaveClass('is-collapsed')
  })

  test('the phone drawer opens, closes on Escape, and closes after picking a page', async () => {
    renderAt()
    const menu = screen.getByRole('button', { name: 'Menu' })
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

  test('the current page is marked', () => {
    renderAt('/templates')
    expect(screen.getByRole('link', { name: 'Templates' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Onboardings' })).not.toHaveAttribute('aria-current')
  })
})
