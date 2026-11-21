import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { Banner, Problems } from './Banner'
import { ProgressBar } from './ProgressBar'
import { StepTracker } from './StepTracker'
import { OnboardingBadge, StepBadge } from './StatusBadge'

test('every step and onboarding status has a glyph and a word, so colour never carries meaning alone', () => {
  for (const [status, word] of [['pending', 'To do'], ['in_progress', 'In progress'], ['done', 'Done'], ['skipped', 'Skipped']] as const) {
    const { container, unmount } = render(<StepBadge status={status} />)
    expect(container.textContent).toContain(word)
    expect(container.querySelector('[aria-hidden="true"]')?.textContent).toBeTruthy()
    unmount()
  }
  for (const [status, word] of [['draft', 'Draft'], ['active', 'Active'], ['paused', 'Paused'], ['completed', 'Completed'], ['archived', 'Archived']] as const) {
    const { container, unmount } = render(<OnboardingBadge status={status} />)
    expect(container.textContent).toContain(word)
    unmount()
  }
})

test('progress is readable as text and exposed to assistive tech', () => {
  render(<ProgressBar progress={{ done: 2, total: 5 }} label="Your progress" />)
  expect(screen.getByText('Your progress: 2 of 5 done')).toBeInTheDocument()
  const bar = screen.getByRole('progressbar', { name: 'Your progress' })
  expect(bar).toHaveAttribute('aria-valuenow', '2')
  expect(bar).toHaveAttribute('aria-valuemax', '5')
})

test('errors are announced as alerts, other messages as status', () => {
  render(<><Banner kind="error">Broken</Banner><Banner kind="ok">Fine</Banner><Problems problems={['One', 'Two']} /></>)
  expect(screen.getAllByRole('alert').length).toBe(2)
  expect(screen.getByRole('status')).toHaveTextContent('Fine')
  expect(screen.getByText('Two')).toBeInTheDocument()
})

test('no problems renders nothing', () => {
  const { container } = render(<Problems problems={[]} />)
  expect(container).toBeEmptyDOMElement()
})

test('the step tracker lists every step in order, marks the next one, and says each status in words', () => {
  render(<StepTracker steps={[
    { key: 'a', title: 'Business details', status: 'done' },
    { key: 'b', title: 'Upload logo', status: 'in_progress' },
    { key: 'c', title: 'Book a call', status: 'pending' },
    { key: 'd', title: 'Optional', status: 'skipped' },
  ]} />)
  const items = screen.getAllByRole('listitem')
  expect(items.map((i) => i.textContent)).toEqual([
    expect.stringContaining('Business details'), expect.stringContaining('Upload logo'), expect.stringContaining('Book a call'), expect.stringContaining('Optional'),
  ])
  expect(items[0]).toHaveTextContent('Done')
  expect(items[1]).toHaveTextContent('In progress, next')
  expect(items[1]).toHaveAttribute('aria-current', 'step')
  expect(items[2]).not.toHaveAttribute('aria-current')
  expect(items[3]).toHaveTextContent('Skipped')
})

test('the step tracker marks nothing as next when every step is finished, and renders nothing with no steps', () => {
  const { container, rerender } = render(<StepTracker steps={[{ key: 'a', title: 'One', status: 'done' }]} />)
  expect(container.querySelector('[aria-current]')).toBeNull()
  rerender(<StepTracker steps={[]} />)
  expect(container.firstChild).toBeNull()
})
