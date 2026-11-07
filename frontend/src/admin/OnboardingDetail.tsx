import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import {
  useAdminComment, useAnswerStep, useClients, useExtendLink, useIssueLink, useLinks, useOnboarding, useOnboardingAction, useRevokeLink, useSend, useStepAction,
} from '../api/admin'
import { ApiError } from '../api/http'
import type { AdminStep, Contact, LinkInfo } from '../api/types'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { CopyButton } from '../components/CopyButton'
import { ProgressBar } from '../components/ProgressBar'
import { OnboardingBadge, StepBadge } from '../components/StatusBadge'
import { dueLabel, formatDateTime } from '../lib/format'
import StepResponse from './StepResponse'
import AiosPanel from './AiosPanel'
import RemindersPanel from './RemindersPanel'

function errText(e: unknown): string {
  return e instanceof ApiError ? [e.message, ...e.problems].join(' ') : 'That did not work.'
}

function IssuedLinks({ links }: { links: LinkInfo[] }) {
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

function LinksPanel({ id, contacts, issued, onIssued }: { id: string; contacts: Contact[]; issued: LinkInfo[]; onIssued: (l: LinkInfo[]) => void }) {
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

function AdminStepCard({ id, step, contact }: { id: string; step: AdminStep; contact?: Contact }) {
  const action = useStepAction(id)
  const answer = useAnswerStep(id)
  const comment = useAdminComment(id)
  // Open when there is something to read or do: an answer, work in progress, or your own internal task.
  const [open, setOpen] = useState(step.response !== null || step.status === 'in_progress' || step.type === 'internal_task')
  const [note, setNote] = useState('')
  const [text, setText] = useState('')
  const [visible, setVisible] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const due = dueLabel(step.due_at, step.status)
  const run = async (fn: () => Promise<unknown>) => { setError(null); try { await fn() } catch (e) { setError(errText(e)) } }

  async function send(e: FormEvent) {
    e.preventDefault()
    await run(async () => { await comment.mutateAsync({ key: step.key, body: text.trim(), client_visible: visible }); setText('') })
  }

  return (
    <li className={`step step-${step.status}`}>
      <button className="step-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="step-toggle-title">{step.title}</span>
        <span className="step-toggle-meta">
          <StepBadge status={step.status} />
          <span className="due">{step.type.replace('_', ' ')}</span>
          {step.visibility === 'internal' && <span className="badge">🔒 Internal. Never shown to the client</span>}
          {contact && <span className="due">For {contact.name}</span>}
          {due && <span className={due.overdue ? 'due due-overdue' : 'due'}>{due.overdue ? '⚠ ' : ''}{due.text}</span>}
        </span>
        <span aria-hidden="true" className="chev">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="step-panel">
          {error && <Banner kind="error">{error}</Banner>}
          {step.type === 'internal_task' && (step.config.checklist ?? []).length > 0 && (
            <ul>{(step.config.checklist as string[]).map((c) => <li key={c}>{c}</li>)}</ul>
          )}
          <StepResponse onboardingId={id} step={step} />
          <div className="row wrap">
            {step.status !== 'done' && step.type === 'internal_task' && (
              <>
                <label className="field-group grow"><span>Note (optional)</span><input value={note} onChange={(e) => setNote(e.target.value)} /></label>
                <button className="btn btn-primary" disabled={answer.isPending} onClick={() => run(() => answer.mutateAsync({ key: step.key, data: { note } }))}>Mark done</button>
              </>
            )}
            {step.status !== 'done' && step.type !== 'internal_task' && <button className="btn" onClick={() => run(() => action.mutateAsync({ key: step.key, action: 'complete' }))}>Mark done</button>}
            {step.status !== 'skipped' && step.status !== 'done' && <button className="btn" onClick={() => run(() => action.mutateAsync({ key: step.key, action: 'skip' }))}>Skip</button>}
            {(step.status === 'done' || step.status === 'skipped') && <button className="btn" onClick={() => run(() => action.mutateAsync({ key: step.key, action: 'reopen' }))}>Reopen</button>}
          </div>
          {step.comments.length > 0 && (
            <ul className="comments">{step.comments.map((c) => (
              <li key={c.id} className={`comment comment-${c.author_kind}`}>
                <div className="comment-meta">{c.author_kind === 'admin' ? 'You' : c.author_label} · {formatDateTime(c.created_at)}{c.client_visible === false ? ' · 🔒 hidden from the client' : ''}</div>
                <div>{c.body}</div>
              </li>
            ))}</ul>
          )}
          {step.visibility === 'client' ? (
            <form onSubmit={send} className="row wrap">
              <label className="field-group grow"><span>Add a comment</span><input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} /></label>
              <label className="check"><input type="checkbox" checked={visible} onChange={(e) => setVisible(e.target.checked)} /> Visible to the client</label>
              <button className="btn" disabled={!text.trim() || comment.isPending}>Add</button>
            </form>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); void run(async () => { await comment.mutateAsync({ key: step.key, body: text.trim(), client_visible: false }); setText('') }) }} className="row wrap">
              <label className="field-group grow"><span>Add a private comment</span><input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} /></label>
              <button className="btn" disabled={!text.trim() || comment.isPending}>Add</button>
            </form>
          )}
        </div>
      )}
    </li>
  )
}

export default function OnboardingDetail() {
  const { id = '' } = useParams()
  const ob = useOnboarding(id)
  const clients = useClients()
  const act = useOnboardingAction(id)
  const send = useSend(id)
  const [issued, setIssued] = useState<LinkInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  if (ob.isPending) return <p>Loading…</p>
  if (ob.isError || !ob.data) return <div className="stack"><LoadError error={ob.error} what="this onboarding" /><Link to="/">← Onboardings</Link></div>
  const o = ob.data
  const client = clients.data?.find((c) => c.id === o.client_id)
  const contacts = client?.contacts ?? []
  const run = async (fn: () => Promise<unknown>) => { setError(null); try { await fn() } catch (e) { setError(errText(e)) } }

  const sections: { key: string; steps: AdminStep[] }[] = []
  for (const s of o.steps) {
    const last = sections[sections.length - 1]
    if (last && last.key === s.section) last.steps.push(s)
    else sections.push({ key: s.section, steps: [s] })
  }
  const pretty = (k: string) => (k ? k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()) : 'Steps')

  return (
    <div className="stack">
      <p><Link to="/">← Onboardings</Link></p>
      <div className="row between wrap">
        <div>
          <h1>{o.title}</h1>
          <p className="help">{client ? <Link to={`/clients/${client.id}`}>{client.name}</Link> : null} · {o.layout} layout</p>
        </div>
        <OnboardingBadge status={o.status} />
      </div>
      <ProgressBar progress={o.progress} />
      {error && <Banner kind="error">{error}</Banner>}
      <div className="row wrap">
        {o.status === 'draft' && (
          <button className="btn btn-primary" disabled={send.isPending || contacts.length === 0} onClick={() => window.confirm('Start this onboarding and make a link for each contact?') && run(async () => setIssued((await send.mutateAsync()).links))}>
            {send.isPending ? 'Sending…' : 'Send to the client'}
          </button>
        )}
        {o.status === 'active' && <button className="btn" onClick={() => run(() => act.mutateAsync('pause'))}>Pause</button>}
        {o.status === 'paused' && <button className="btn btn-primary" onClick={() => run(() => act.mutateAsync('resume'))}>Resume</button>}
        {o.status !== 'archived' && <button className="btn" onClick={() => window.confirm('Archive this onboarding? Client links stop working.') && run(() => act.mutateAsync('archive'))}>Archive</button>}
      </div>
      {o.attention === 'nudges_exhausted' && <Banner kind="warn"><strong>Needs you.</strong> This client hasn't replied to the reminders, and they have stopped. A call or a message from you might help.</Banner>}
      {o.attention === 'unreachable' && <Banner kind="warn"><strong>Needs you.</strong> There's no email address or consented phone number to reach this client on, so reminders can't go out. <Link to={`/clients/${o.client_id}`}>Add one on the client page</Link>.</Banner>}
      {o.status === 'draft' && contacts.length === 0 && <Banner kind="warn">This client has no contacts yet, so there is nobody to send a link to. <Link to={`/clients/${o.client_id}`}>Add a contact</Link>.</Banner>}
      {o.status === 'draft' && <Banner>This is a draft. The client can't see anything until you send it.</Banner>}

      {sections.map((g, i) => (
        <section key={`${g.key}-${i}`} className="section" aria-label={pretty(g.key)}>
          <h2>{pretty(g.key)}</h2>
          <ul className="steps">{g.steps.map((s) => <AdminStepCard key={s.id} id={id} step={s} contact={contacts.find((c) => c.id === s.assignee_contact_id)} />)}</ul>
        </section>
      ))}

      <LinksPanel id={id} contacts={contacts} issued={issued} onIssued={setIssued} />
      <RemindersPanel ob={o} />
      <AiosPanel ob={o} />
    </div>
  )
}
