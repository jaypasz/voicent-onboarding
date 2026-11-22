import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import {
  useAdminComment, useAnswerStep, useOrgSettings, useSchedule, useSetOwner, useSetStepFollower, useSignOff, useTeam, useClients, useOnboarding,
  useOnboardingAction, useSend, useStepAction,
} from '../api/admin'
import { ApiError } from '../api/http'
import type { AdminStage, AdminStep, Contact, LinkInfo, TeamMember } from '../api/types'
import { memberLabel } from '../lib/team'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { ProgressBar } from '../components/ProgressBar'
import { StageTracker, StepTracker } from '../components/StepTracker'
import { StepBadge } from '../components/StatusBadge'
import { STAGE_STATE, dayRange, dueLabel, formatDate, formatDateTime, formatDay } from '../lib/format'
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

/** A popup calendar for the day a step starts and the day it is due. Each pick is saved at once. */
function Schedule({ id, step, disabled }: { id: string; step: AdminStep; disabled: boolean }) {
  const schedule = useSchedule(id)
  const [error, setError] = useState<string | null>(null)
  const [start, setStart] = useState(step.start_on ?? '')
  const [due, setDue] = useState(step.due_on ?? '')
  useEffect(() => { setStart(step.start_on ?? ''); setDue(step.due_on ?? '') }, [step.start_on, step.due_on])
  // Typing a year into a date field passes through 0002, 0020 and 0202 on the way to 2026: only a real year is saved.
  const ready = (d: string) => d === '' || Number(d.slice(0, 4)) >= 2000
  async function save(next: { start_on: string; due_on: string }) {
    setStart(next.start_on)
    setDue(next.due_on)
    if (!ready(next.start_on) || !ready(next.due_on)) return
    setError(null)
    try { await schedule.mutateAsync({ key: step.key, start_on: next.start_on || null, due_on: next.due_on || null }) } catch (e) { setError(errText(e)) }
  }
  return (
    <fieldset className="schedule" disabled={disabled || schedule.isPending}>
      <legend>Schedule</legend>
      <div className="row wrap">
        <label className="field-group"><span>Starts</span>
          <input type="date" value={start} max={due || undefined} onChange={(e) => void save({ start_on: e.target.value, due_on: due })} />
        </label>
        <label className="field-group"><span>Due</span>
          <input type="date" value={due} min={start || undefined} onChange={(e) => void save({ start_on: start, due_on: e.target.value })} />
        </label>
        {(start || due) && <button type="button" className="btn btn-small" onClick={() => void save({ start_on: '', due_on: '' })}>Clear dates</button>}
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </fieldset>
  )
}

function StageHeader({ id, stage, index, previous, canSign, onError }: {
  id: string; stage: AdminStage; index: number; previous?: AdminStage; canSign: boolean; onError: (e: string | null) => void
}) {
  const sign = useSignOff(id)
  const { glyph, label } = STAGE_STATE[stage.state]
  const dates = dayRange(stage.start_on, stage.due_on)
  const run = async (withdraw: boolean) => { onError(null); try { await sign.mutateAsync({ key: stage.key, withdraw }) } catch (e) { onError(errText(e)) } }
  return (
    <div className="stage-summary">
      <h2 id={`stage-${stage.key}`}><span className="stage-number" aria-hidden="true">{index + 1}</span> {stage.title}</h2>
      <div className="row wrap stage-meta">
        <span className={`badge stage-${stage.state}`}><span aria-hidden="true">{glyph}</span> {label}</span>
        <span className="due">{stage.progress.done} of {stage.progress.total} done</span>
        {dates && <span className="due">{dates}</span>}
        {!stage.signoff && <span className="due">No sign-off needed</span>}
      </div>
      {stage.state === 'locked' && previous && (
        <p className="help">The client sees these steps but can't answer them until “{previous.title}” is signed off. Your team can work on them now.</p>
      )}
      {stage.state === 'ready' && (
        <div className="row wrap">
          <button type="button" className="btn btn-primary" disabled={!canSign || sign.isPending} onClick={() => void run(false)}>
            {sign.isPending ? 'Signing off…' : `Sign off “${stage.title}”`}
          </button>
          <p className="help">{canSign ? 'Every step is finished. Signing off opens the next stage to the client.' : 'Every step is finished. An admin or a manager signs it off.'}</p>
        </div>
      )}
      {stage.state === 'signed_off' && (
        <div className="row wrap">
          <p className="help">✓ Signed off by {stage.signed_by || 'your team'} on {formatDate(stage.signed_at)}.</p>
          {canSign && (
            <button type="button" className="btn btn-small" disabled={sign.isPending}
              onClick={() => window.confirm(`Withdraw the sign-off of “${stage.title}”? The stages after it lock again for the client.`) && void run(true)}>Withdraw sign-off</button>
          )}
        </div>
      )}
    </div>
  )
}

function AdminStepCard({ id, step, contact, members, closed }: { id: string; step: AdminStep; contact?: Contact; members: TeamMember[]; closed: boolean }) {
  const follower = useSetStepFollower(id)
  const ours = members.find((m) => m.id === step.team_assignee_id)
  const action = useStepAction(id)
  const answer = useAnswerStep(id)
  // our own task: it is ours to work through here, so it is open and gets the checklist and a note box
  const teamTask = step.type === 'task' && step.visibility === 'internal'
  const comment = useAdminComment(id)
  // Open when there is something to read or do: an answer, work in progress, or your own internal task.
  const [open, setOpen] = useState(step.response !== null || step.status === 'in_progress' || teamTask)
  const [note, setNote] = useState('')
  const [text, setText] = useState('')
  const [visible, setVisible] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const due = dueLabel(step.due_at, step.status, undefined, step.due_on)
  const items: string[] = step.type === 'task' ? step.config.checklist ?? [] : []
  const ticked: number[] = (step.response?.data.checked as number[] | undefined) ?? []
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
          {step.start_on && step.status !== 'done' && step.status !== 'skipped' && <span className="due">Starts {formatDay(step.start_on)}</span>}
          {due && <span className={due.overdue ? 'due due-overdue' : 'due'}>{due.overdue ? '⚠ ' : ''}{due.text}</span>}
          {step.locked && step.visibility === 'client' && <span className="due">🔒 Not open to the client yet</span>}
        </span>
        <span aria-hidden="true" className="chev">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="step-panel">
          {error && <Banner kind="error">{error}</Banner>}
          <Schedule id={id} step={step} disabled={closed} />
          {members.length > 0 && (
            <TeamSelect label="Followed up by (our side)" value={step.team_assignee_id} members={members} disabled={follower.isPending}
              onChange={(member_id) => void run(() => follower.mutateAsync({ key: step.key, member_id }))} />
          )}
          {teamTask && step.config.instructions && <p style={{ whiteSpace: 'pre-wrap' }}>{step.config.instructions}</p>}
          {teamTask && items.length > 0 && (
            <ul className="checklist" aria-label="Checklist">{items.map((c, i) => (
              <li key={c}><label className="check">
                <input type="checkbox" checked={ticked.includes(i)} disabled={answer.isPending}
                  onChange={(e) => void run(() => answer.mutateAsync({ key: step.key, data: { checked: e.target.checked ? [...new Set([...ticked, i])] : ticked.filter((x) => x !== i) } }))} /> <span>{c}</span>
              </label></li>
            ))}</ul>
          )}
          {!teamTask && <StepResponse onboardingId={id} step={step} />}
          {teamTask && step.response?.data.note && <p>{step.response.data.note}</p>}
          <div className="row wrap">
            {step.status !== 'done' && teamTask && (
              <>
                <label className="field-group grow"><span>Note (optional)</span><input value={note} onChange={(e) => setNote(e.target.value)} /></label>
                <button className="btn btn-primary" disabled={answer.isPending} onClick={() => run(() => answer.mutateAsync({ key: step.key, data: { note, done: true, ...(items.length ? { checked: items.map((_, i) => i) } : {}) } }))}>Mark done</button>
              </>
            )}
            {step.status !== 'done' && !teamTask && <button className="btn" onClick={() => run(() => action.mutateAsync({ key: step.key, action: 'complete' }))}>Mark done</button>}
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
  const org = useOrgSettings()
  const [issued, setIssued] = useState<LinkInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  if (ob.isPending) return <p>Loading…</p>
  if (ob.isError || !ob.data) return <div className="stack"><LoadError error={ob.error} what="this onboarding" /><Link to="/">← Onboardings</Link></div>
  const o = ob.data
  const client = clients.data?.find((c) => c.id === o.client_id)
  const contacts = client?.contacts ?? []
  const members = team.data?.members ?? []
  const run = async (fn: () => Promise<unknown>) => { setError(null); try { await fn() } catch (e) { setError(errText(e)) } }
  const role = org.data?.role
  const canSign = !role || role === 'admin' || role === 'manager'  // the server checks again
  const closed = o.status === 'archived'

  // The steps grouped by stage, in stage order (the server sends them in that order); steps outside a stage come last.
  const stages = o.stages ?? []
  const inStage = new Set(stages.map((st) => st.key))
  const loose = o.steps.filter((s) => !inStage.has(s.section))
  const card = (s: AdminStep) => <AdminStepCard key={s.id} id={id} step={s} contact={contacts.find((c) => c.id === s.assignee_contact_id)} members={members} closed={closed} />

  return (
    <div className="stack">
      <ProgressBar progress={o.progress} />
      {stages.length > 0
        ? <StageTracker stages={stages.map((st) => ({ key: st.key, title: st.title, state: st.state, detail: `${st.progress.done}/${st.progress.total}` }))} />
        : <StepTracker steps={o.steps} />}
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

      {stages.map((st, i) => (
        <section key={st.key} className={`section stage-section stage-section-${st.state}`} aria-labelledby={`stage-${st.key}`}>
          <StageHeader id={id} stage={st} index={i} previous={stages.slice(0, i).reverse().find((p) => p.signoff && p.state !== 'signed_off')} canSign={canSign} onError={setError} />
          <ul className="steps">{o.steps.filter((s) => s.section === st.key).map(card)}</ul>
        </section>
      ))}
      {loose.length > 0 && (
        <section className="section" aria-labelledby="stage-none">
          <h2 id="stage-none">{stages.length ? 'Not in a stage' : 'Steps'}</h2>
          <ul className="steps">{loose.map(card)}</ul>
        </section>
      )}

    </div>
  )
}
