import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useCreateTask, useDeleteTask, useTasks, useTeam, useUpdateTask, type TaskFilter } from '../api/admin'
import { ApiError } from '../api/http'
import type { Task, TeamMember } from '../api/types'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { formatDate } from '../lib/format'
import { memberLabel } from '../lib/team'

const today = () => new Date().toISOString().slice(0, 10)
const overdue = (t: Task) => !t.done_at && !!t.due_on && t.due_on < today()
const msg = (e: unknown) => (e instanceof ApiError ? e.message : 'That did not work.')

function TaskRow({ t, members, clientName }: { t: Task; members: TeamMember[]; clientName?: string }) {
  const update = useUpdateTask()
  const del = useDeleteTask()
  const [error, setError] = useState<string | null>(null)
  const run = async (fn: () => Promise<unknown>) => { setError(null); try { await fn() } catch (e) { setError(msg(e)) } }
  return (
    <li className={`card task${t.done_at ? ' task-done' : ''}`}>
      <div className="row wrap">
        <label className="check grow">
          <input type="checkbox" checked={!!t.done_at} disabled={update.isPending} onChange={(e) => void run(() => update.mutateAsync({ id: t.id, patch: { done: e.target.checked } }))} />
          <span><strong>{t.title}</strong>{clientName && <> · <Link to={`/clients/${t.client_id}`}>{clientName}</Link></>}</span>
        </label>
        {t.due_on && <span className={`due${overdue(t) ? ' due-overdue' : ''}`}>{overdue(t) ? 'Overdue: ' : 'Due '}{formatDate(t.due_on)}</span>}
        <select aria-label={`Who does "${t.title}"`} value={t.assignee_id ?? ''} onChange={(e) => void run(() => update.mutateAsync({ id: t.id, patch: { assignee_id: e.target.value || null } }))}>
          <option value="">Nobody</option>
          {members.map((m) => <option key={m.id} value={m.id}>{memberLabel(m)}{m.is_you ? ' (you)' : ''}</option>)}
        </select>
        <button className="btn btn-small" disabled={del.isPending} onClick={() => void run(() => del.mutateAsync(t.id))} aria-label={`Delete "${t.title}"`}>Delete</button>
      </div>
      {error && <Banner kind="error">{error}</Banner>}
    </li>
  )
}

/** The team's to-dos. Ours alone: a client never sees them and they never go to Voicent-App or the AIOS board. */
export function TasksPanel({ filter, clientId, clientNames, showFinished = true }: { filter?: TaskFilter; clientId?: string; clientNames?: Record<string, string>; showFinished?: boolean }) {
  const tasks = useTasks(filter)
  const team = useTeam()
  const create = useCreateTask()
  const members = team.data?.members ?? []
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')
  const [who, setWho] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function add(e: FormEvent) {
    e.preventDefault()
    if (!clientId) return
    setError(null)
    try {
      await create.mutateAsync({ client_id: clientId, title: title.trim(), due_on: due || null, assignee_id: who || null })
      setTitle(''); setDue(''); setWho('')
    } catch (err) { setError(msg(err)) }
  }

  const rows = (tasks.data ?? []).filter((t) => showFinished || !t.done_at)
  return (
    <div className="stack">
      {clientId && (
        <form onSubmit={add} className="row wrap" aria-label="Add a task">
          <label className="field-group grow"><span>New task</span><input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required /></label>
          <label className="field-group"><span>Due</span><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
          <label className="field-group"><span>Who</span>
            <select value={who} onChange={(e) => setWho(e.target.value)}>
              <option value="">Nobody</option>
              {members.map((m) => <option key={m.id} value={m.id}>{memberLabel(m)}{m.is_you ? ' (you)' : ''}</option>)}
            </select>
          </label>
          <button className="btn btn-primary" disabled={create.isPending || !title.trim()}>Add task</button>
        </form>
      )}
      {error && <Banner kind="error">{error}</Banner>}
      {tasks.isError && <LoadError error={tasks.error} what="tasks" />}
      {tasks.isSuccess && rows.length === 0 && <Banner>No tasks.</Banner>}
      <ul className="cards">{rows.map((t) => <TaskRow key={t.id} t={t} members={members} clientName={clientNames?.[t.client_id]} />)}</ul>
    </div>
  )
}
