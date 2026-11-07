import { describe, expect, test } from 'vitest'
import { dueLabel, formatBytes, timeAgo } from './format'
import { safeHttpsUrl } from './links'
import { problemsByField } from './problems'
import { extensionOf, fileProblem } from './uploads'

describe('safeHttpsUrl', () => {
  test('only plain https becomes a link', () => {
    expect(safeHttpsUrl('https://cal.example.com/book')).toBe('https://cal.example.com/book')
    for (const bad of ['http://example.com', 'javascript:alert(1)', 'data:text/html,<script>', 'ftp://x.test', '//evil.test', 'not a url', '', null, undefined, 5]) {
      expect(safeHttpsUrl(bad)).toBeNull()
    }
  })
})

describe('dueLabel', () => {
  const now = new Date('2026-11-10T12:00:00Z')
  test('says due or overdue, and nothing for finished steps', () => {
    expect(dueLabel('2026-11-12T00:00:00Z', 'pending', now)).toMatchObject({ overdue: false })
    expect(dueLabel('2026-11-12T00:00:00Z', 'pending', now)!.text).toMatch(/^Due /)
    expect(dueLabel('2026-11-05T00:00:00Z', 'in_progress', now)).toMatchObject({ overdue: true })
    expect(dueLabel('2026-11-05T00:00:00Z', 'in_progress', now)!.text).toMatch(/^Overdue since /)
    expect(dueLabel('2026-11-05T00:00:00Z', 'done', now)).toBeNull()
    expect(dueLabel('2026-11-05T00:00:00Z', 'skipped', now)).toBeNull()
    expect(dueLabel(null, 'pending', now)).toBeNull()
    expect(dueLabel('garbage', 'pending', now)).toBeNull()
  })
})

test('formatBytes and timeAgo', () => {
  expect(formatBytes(500)).toBe('500 B')
  expect(formatBytes(2048)).toBe('2 KB')
  expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB')
  const now = new Date('2026-11-10T12:00:00Z')
  expect(timeAgo('2026-11-10T11:59:50Z', now)).toBe('just now')
  expect(timeAgo('2026-11-10T11:30:00Z', now)).toBe('30 min ago')
  expect(timeAgo('2026-11-10T09:00:00Z', now)).toBe('3 h ago')
  expect(timeAgo('2026-11-07T12:00:00Z', now)).toBe('3 d ago')
})

test('problems are matched back to the fields they are about', () => {
  const fields = [
    { key: 'name', label: 'Business name', type: 'text' as const },
    { key: 'email', label: 'Email address', type: 'email' as const },
  ]
  const { byKey, rest } = problemsByField(['Business name: this is required.', "Email address: doesn't look like an email address.", "'x' isn't a question on this form."], fields)
  expect(byKey).toEqual({ name: 'this is required.', email: "doesn't look like an email address." })
  expect(rest).toEqual(["'x' isn't a question on this form."])
})

describe('uploads', () => {
  test('the same allow-list as the server, and SVG is never in it', () => {
    expect(extensionOf('Logo.PNG')).toBe('png')
    expect(extensionOf('noext')).toBe('')
    expect(fileProblem({ name: 'logo.svg', size: 10 }, ['png', 'pdf'], 5)).toMatch(/isn't allowed/)
    expect(fileProblem({ name: 'a.png', size: 0 }, ['png'], 5)).toMatch(/empty/)
    expect(fileProblem({ name: 'a.png', size: 6 * 1024 * 1024 }, ['png'], 5)).toMatch(/up to 5 MB/)
    expect(fileProblem({ name: 'a.PNG', size: 1000 }, ['png'], 5)).toBeNull()
  })
})
