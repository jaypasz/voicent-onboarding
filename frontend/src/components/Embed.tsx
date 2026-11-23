import { useState } from 'react'
import type { ExternalLink, Resource } from '../api/types'
import { safeHttpsUrl } from '../lib/links'
import { Icon } from './Icon'

/** The hosts an embed may point at. The server builds embed addresses only for these (app/embeds.py EMBED_HOSTS); this is a
 * second check, so an iframe is never drawn for anything else whatever the data says. */
export const EMBED_HOSTS = ['www.loom.com', 'www.youtube-nocookie.com', 'player.vimeo.com', 'www.figma.com', 'docs.google.com', 'drive.google.com']
const VIDEO = new Set(['loom', 'youtube', 'vimeo'])

export function safeEmbedUrl(value: unknown): string | null {
  const url = safeHttpsUrl(value)
  return url && EMBED_HOSTS.includes(new URL(url).hostname) ? url : null
}

export const isVideo = (info: ExternalLink | null | undefined): boolean => !!info && VIDEO.has(info.provider)

const PROVIDER: Record<string, string> = {
  loom: 'Loom', youtube: 'YouTube', vimeo: 'Vimeo', figma: 'Figma', google_doc: 'Google Docs', google_sheet: 'Google Sheets',
  google_slides: 'Google Slides', google_drive: 'Google Drive', notion: 'Notion',
}

/** Another tool's page inside ours. Sandboxed; sends only our origin as the referrer, never the page address (in the portal
 * that address is the client's key). Always with a plain link under it, for when the frame is blocked or too small. */
export function Embed({ info, title }: { info: ExternalLink; title: string }) {
  const src = safeEmbedUrl(info.embed_url)
  const href = safeHttpsUrl(info.href)
  return (
    <figure className="embed">
      {src && (
        <div className={isVideo(info) ? 'embed-frame embed-video' : 'embed-frame embed-doc'}>
          <iframe src={src} title={`${title} (${info.kind})`} loading="lazy" referrerPolicy="strict-origin"
            sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-presentation"
            allow="fullscreen; picture-in-picture; clipboard-write" />
        </div>
      )}
      <figcaption>
        {href ? <a href={href} target="_blank" rel="noopener noreferrer">Open in {PROVIDER[info.provider] ?? 'a new tab'} ↗</a> : <span className="help">{info.kind}</span>}
      </figcaption>
    </figure>
  )
}

function ResourceItem({ item }: { item: Resource }) {
  const [shown, setShown] = useState(false)
  const href = safeHttpsUrl(item.href)
  const canShow = !!safeEmbedUrl(item.embed_url)
  return (
    <li className="resource">
      <div className="resource-row">
        <span className="resource-icon"><Icon name={isVideo(item) ? 'info_video' : 'link'} /></span>
        <span className="resource-text">
          {href ? <a href={href} target="_blank" rel="noopener noreferrer">{item.label} ↗</a> : <span>{item.label}</span>}
          <span className="help">{item.kind}</span>
        </span>
        {canShow && (
          <button type="button" className="btn btn-small" aria-expanded={shown} onClick={() => setShown(!shown)}>
            {shown ? 'Hide' : isVideo(item) ? 'Watch here' : 'View here'}
          </button>
        )}
      </div>
      {shown && <Embed info={item} title={item.label} />}
    </li>
  )
}

/** A step's links. Each opens in a new tab; one that can be shown inside the page does so only when asked, so a checklist
 * doesn't load a dozen other sites at once. */
export function Resources({ items, heading = 'Helpful links' }: { items: Resource[] | undefined; heading?: string }) {
  if (!items?.length) return null
  return (
    <section className="resources" aria-label={heading}>
      <h4>{heading}</h4>
      <ul>{items.map((r, i) => <ResourceItem key={`${r.href}-${i}`} item={r} />)}</ul>
    </section>
  )
}
