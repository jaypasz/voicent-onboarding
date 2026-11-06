import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.tsx'

afterEach(() => vi.unstubAllGlobals())

test('shows the server as up when /api/health answers', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  render(<App />)
  expect(await screen.findByText(/✓ up/)).toBeInTheDocument()
})

test('says so when the server is not reachable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')))
  render(<App />)
  expect(await screen.findByText(/✗ not reachable/)).toBeInTheDocument()
})
