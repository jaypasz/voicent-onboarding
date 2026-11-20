import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import {
  useAdminComment, useAnswerStep, useSetOwner, useSetStepFollower, useTeam, useClients, useOnboarding, useOnboardingAction, useSend, useStepAction,
} from '../api/admin'
import { ApiError } from '../api/http'
import type { AdminStep, Contact, LinkInfo, TeamMember } from '../api/types'
import { memberLabel } from '../lib/team'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { ProgressBar } from '../components/ProgressBar'
import { StepBadge } from '../components/StatusBadge'
import { dueLabel, formatDateTime } from '../lib/format'
import StepResponse from './StepResponse'
import { IssuedLinks } from './LinksPanel'

function errText(e: unknown): string {
  return e instanceof ApiError ? [e.message, ...e.problems].join(' ') : 'That did not work.'
}

function TeamSelect({ label, value, members, onChange, disabled }: { label: string; value: string | null | undefined; members: TeamMember[]; onChange: (id: string | null) => void; disabled?: boolean }) {
  return (
    <label className="field-group"><span>{label}</span>
      <select value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">Nobody</option>
        {members.map((m) => <option key={m.id} value={m.id}>{memberLabel(m)}{m.is_you ? ' (you)' : ''}</option>)}
      </select>
    </label>
  )
}

function AdminStepCard({ id, step, contact, members }: { id: string; step: AdminStep; contact?: Contact; members: TeamMember[] }) {
  const follower = useSetStepFollower(id)
  const ours = members.find((m) => m.id === step.team_assignee_id)
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
          {ours && <span className="due">Ours: {memberLabel(ours)}</span>}
          {due && <span className={due.overdue ? 'due due-overdue' : 'due'}>{due.overdue ? '⚠ ' : ''}{due.text}</span>}
        </span>
        <span aria-hidden="true" className="chev">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="step-panel">
          {error && <Banner kind="error">{error}</Banner>}
          {members.length > 0 && (
            <TeamSelect label="Followed up by (our side)" value={step.team_assignee_id} members={members} disabled={follower.isPending}
              onChange={(member_id) => void run(() => follower.mutateAsync({ key: step.key, member_id }))} />
          )}
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
  const team = useTeam()
  const owner = useSetOwner(id)
  const [issued, setIssued] = useState<LinkInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  if (ob.isPending) return <p>Loading…</p>
  if (ob.isError || !ob.data) return <div className="stack"><LoadError error={ob.error} what="this onboarding" /><Link to="/">← Onboardings</Link></div>
  const o = ob.data
  const client = clients.data?.find((c) => c.id === o.client_id)
  const contacts = client?.contacts ?? []
  const members = team.data?.members ?? []
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
      <ProgressBar progress={o.progress} />
      {members.length > 0 && (
        <div className="owner-row">
          <TeamSelect label="Looked after by" value={o.owner_member_id} members={members} disabled={owner.isPending}
            onChange={(member_id) => void run(() => owner.mutateAsync(member_id))} />
          <p className="help">They're told when it finishes, when the client goes quiet, and when the client answers a step nobody else follows up.</p>
        </div>
      )}
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
        <Link className="btn" to={`/onboardings/${id}/preview`}>See it as the client does</Link>
      </div>
      {issued.length > 0 && <IssuedLinks links={issued} />}
      {o.attention === 'nudges_exhausted' && <Banner kind="warn"><strong>Needs you.</strong> This client hasn't replied to the reminders, and they have stopped. A call or a message from you might help.</Banner>}
      {o.attention === 'unreachable' && <Banner kind="warn"><strong>Needs you.</strong> There's no email address or consented phone number to reach this client on, so reminders can't go out. <Link to={`/clients/${o.client_id}`}>Add one on the client page</Link>.</Banner>}
      {o.status === 'draft' && contacts.length === 0 && <Banner kind="warn">This client has no contacts yet, so there is nobody to send a link to. <Link to={`/clients/${o.client_id}`}>Add a contact</Link>.</Banner>}
      {o.status === 'draft' && <Banner>This is a draft. The client can't see anything until you send it, and you can still <Link to={`/onboardings/${id}/steps`}>change the steps</Link>.</Banner>}

      {sections.map((g, i) => (
        <section key={`${g.key}-${i}`} className="section" aria-label={pretty(g.key)}>
          <h2>{pretty(g.key)}</h2>
          <ul className="steps">{g.steps.map((s) => <AdminStepCard key={s.id} id={id} step={s} contact={contacts.find((c) => c.id === s.assignee_contact_id)} members={members} />)}</ul>
        </section>
      ))}

    </div>
  )
}
