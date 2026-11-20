import { useState } from 'react'
import { useExtendLink, useIssueLink, useLinks, useRevokeLink } from '../api/admin'
import { ApiError } from '../api/http'
import type { Contact, LinkInfo } from '../api/types'
import { Banner } from '../components/Banner'
import { CopyButton } from '../components/CopyButton'
import { formatDateTime } from '../lib/format'

function errText(e: unknown): string {
  return e instanceof ApiError ? [e.message, ...e.problems].join(' ') : 'That did not work.'
}

export function IssuedLinks({ links }: { links: LinkInfo[] }) {
  return (
    <Banner kind="warn">
      <strong>Copy these links now. They can't be shown again.</strong> Each one is for one person; anyone with a link can see and answer this onboarding as that person.
      <ul className="issued">
        {links.map((l) => (
          <li key={l.id}>
            <div>{l.contact_name || 'Link'}</div>
            <input readOnly value={l.url} aria-label={`Link for ${l.contact_name}`} onFocus={(e) => e.currentTarget.select()} />
            <CopyButton text={l.url ?? ''} />
          </li>
        ))}
      </ul>
    </Banner>
  )
}

export function LinksPanel({ id, contacts, issued, onIssued }: { id: string; contacts: Contact[]; issued: LinkInfo[]; onIssued: (l: LinkInfo[]) => void }) {
  const links = useLinks(id)
  const issue = useIssueLink(id)
  const revoke = useRevokeLink(id)
  const extend = useExtendLink(id)
  const [contactId, setContactId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const run = async (fn: () => Promise<unknown>) => { setError(null); try { await fn() } catch (e) { setError(errText(e)) } }

  return (
    <section className="stack" aria-labelledby="links-h">
      <h2 id="links-h">Client links</h2>
      {issued.length > 0 && <IssuedLinks links={issued} />}
      {error && <Banner kind="error">{error}</Banner>}
      {links.data?.length === 0 && <p className="help">No links yet. They are made when you send the onboarding, or you can make one below.</p>}
      <ul className="cards">
        {links.data?.map((l) => (
          <li key={l.id} className="card row between wrap">
            <div>
              <strong>{l.contact_name}</strong>{' '}
              <span className="badge">{l.revoked_at ? '✕ Revoked' : l.usable ? '✓ Works' : '⚠ Expired'}</span>
              <div className="help">Expires {formatDateTime(l.expires_at)}{l.last_used_at ? ` · last opened ${formatDateTime(l.last_used_at)}` : ' · not opened yet'}</div>
            </div>
            {!l.revoked_at && (
              <div className="row">
                <button className="btn btn-small" onClick={() => run(() => extend.mutateAsync({ linkId: l.id, days: 30 }))}>Extend 30 days</button>
                <button className="btn btn-small" onClick={() => window.confirm(`Revoke ${l.contact_name}'s link? It stops working at once.`) && run(() => revoke.mutateAsync(l.id))}>Revoke</button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {contacts.length > 0 && (
        <div className="row wrap">
          <label className="field-group"><span>Make another link for</span>
            <select value={contactId} onChange={(e) => setContactId(e.target.value)}>
              <option value="">Choose a contact…</option>
              {contacts.map((c) => <option key={c.id} value={c.id}>{c.name}{c.role ? ` (${c.role})` : ''}</option>)}
            </select>
          </label>
          <button className="btn" disabled={!contactId || issue.isPending} onClick={() => run(async () => { onIssued([...issued, { ...(await issue.mutateAsync(contactId)), contact_name: contacts.find((c) => c.id === contactId)?.name ?? '' }]); setContactId('') })}>Make link</button>
        </div>
      )}
    </section>
  )
}
