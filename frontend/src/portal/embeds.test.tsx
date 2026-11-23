import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import type { ExternalLink, Resource } from '../api/types'
import { ConfigEditor } from '../builder/ConfigEditor'
import { STEP_KINDS, clean, type StepDoc } from '../builder/doc'
import { Resources, safeEmbedUrl } from '../components/Embed'
import { step } from '../test/helpers'
import InfoVideoStep from './steps/InfoVideoStep'

const loom: ExternalLink = { provider: 'loom', kind: 'Loom video', href: 'https://www.loom.com/share/abc0123456', embed_url: 'https://www.loom.com/embed/abc0123456' }
const notion: Resource = { label: 'The brief', provider: 'notion', kind: 'Notion page', href: 'https://acme.notion.site/Brief-1', embed_url: null }

describe('embeds', () => {
  test('only an https address on a known embed host is ever framed', () => {
    expect(safeEmbedUrl('https://www.loom.com/embed/x')).toBe('https://www.loom.com/embed/x')
    expect(safeEmbedUrl('https://evil.test/embed/x')).toBeNull()
    expect(safeEmbedUrl('http://www.loom.com/embed/x')).toBeNull()
    expect(safeEmbedUrl('javascript:alert(1)')).toBeNull()
    expect(safeEmbedUrl(null)).toBeNull()
  })

  test('a watch-or-read step shows the video sandboxed, never sends the page address, and finishes when watched', async () => {
    const submit = vi.fn(async () => {})
    render(<InfoVideoStep step={step({ key: 'intro', type: 'info_video', title: 'Welcome', config: { instructions: 'Two minutes.' }, media: loom })} submit={submit} busy={false} problems={[]} />)
    const frame = screen.getByTitle('Welcome (Loom video)')
    expect(frame).toHaveAttribute('src', 'https://www.loom.com/embed/abc0123456')
    expect(frame).toHaveAttribute('referrerpolicy', 'strict-origin')
    expect(frame.getAttribute('sandbox')).not.toContain('allow-top-navigation')
    expect(screen.getByRole('link', { name: /Open in Loom/ })).toHaveAttribute('rel', 'noopener noreferrer')
    await userEvent.click(screen.getByRole('button', { name: "I've watched it" }))
    expect(submit).toHaveBeenCalledWith({ seen: true })
  })

  test('an embed address on another host is not framed, and a document says "read"', () => {
    const bad = { ...loom, provider: 'google_doc', kind: 'Google Doc', embed_url: 'https://evil.test/frame' }
    const { container } = render(<InfoVideoStep step={step({ type: 'info_video', title: 'Brief', config: {}, media: bad })} submit={async () => {}} busy={false} problems={[]} />)
    expect(container.querySelector('iframe')).toBeNull()
    expect(screen.getByRole('button', { name: "I've read it" })).toBeInTheDocument()
  })

  test('once seen it says so, and a read-only step has no button', () => {
    render(<InfoVideoStep step={step({ type: 'info_video', config: {}, media: loom, can_write: false, response: { seen: true } })} submit={async () => {}} busy={false} problems={[]} />)
    expect(screen.getByText(/Watched/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
  })

  test('links open in a new tab, an embeddable one shows here only when asked, and a bad address is plain text', async () => {
    const items: Resource[] = [{ ...loom, label: 'Walkthrough' }, notion, { ...notion, label: 'Odd', href: 'javascript:alert(1)' }]
    const { container } = render(<Resources items={items} />)
    const list = screen.getByRole('region', { name: 'Helpful links' })
    expect(within(list).getByRole('link', { name: /The brief/ })).toHaveAttribute('target', '_blank')
    expect(within(list).queryByRole('link', { name: /Odd/ })).toBeNull()
    expect(within(list).getByText('Odd')).toBeInTheDocument()
    expect(within(list).getAllByRole('button')).toHaveLength(1)  // Notion can't be shown inside the page
    expect(container.querySelector('iframe')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Watch here' }))
    expect(screen.getByTitle('Walkthrough (Loom video)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide' })).toHaveAttribute('aria-expanded', 'true')
  })

  test('no links, nothing shown', () => {
    const { container } = render(<Resources items={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('in the builder', () => {
  test('"Watch or read" is in the menu with its address setting', async () => {
    expect(STEP_KINDS.map((k) => k.label)).toContain('Watch or read')
    const onChange = vi.fn()
    render(<ConfigEditor type="info_video" config={{ url: '' }} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText(/^Address/), 'h')
    expect(onChange).toHaveBeenLastCalledWith({ url: 'h' })
  })

  test('links are cleaned before saving: blank rows dropped, an empty name left out, builder ids stripped', () => {
    const s: StepDoc = { _uid: 'u1', key: 'a', type: 'form', title: 'A', config: {}, resources: [
      { _uid: 'r1', label: '  Guide ', url: ' https://www.figma.com/design/AbCdEfGhIjKl/G ' }, { _uid: 'r2', label: '', url: 'https://acme.notion.site/x' }, { _uid: 'r3', label: '', url: '' },
    ] }
    expect(clean([s])[0].resources).toEqual([{ label: 'Guide', url: 'https://www.figma.com/design/AbCdEfGhIjKl/G' }, { url: 'https://acme.notion.site/x' }])
  })
})
