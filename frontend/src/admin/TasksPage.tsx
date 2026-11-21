import { useState } from 'react'
import { Link } from 'react-router'
import { useClients, useTeam, useTeamStepTasks } from '../api/admin'
import type { TeamMember, TeamStepTask } from '../api/types'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { dueLabel } from '../lib/format'
import { memberLabel } from '../lib/team'
import { TasksPanel } from './TasksPanel'

function StepTaskRow({ t, names, members }: { t: TeamStepTask; names: Record<string, string>; members: TeamMember[] }) {
  const due = dueLabel(t.due_at, t.status)
  const who = members.find((m) => m.id === t.team_assignee_id)
  return (
    <li className="card task">
      <div className="row wrap">
        <span className="grow"><strong><Link to={`/onboardings/${t.onboarding_id}#step-${t.key}`}>{t.title}</Link></strong>{names[t.client_id] && <> · <Link to={`/clients/${t.client_id}`}>{names[t.client_id]}</Link></>}</span>
        <div className="row wrap task-meta">
          {due && <span className={due.overdue ? 'due due-overdue' : 'due'}>{due.overdue ? '⚠ ' : ''}{due.text}</span>}
          <span className="due">{who ? memberLabel(who) : 'Nobody'}</span>
        </div>
      </div>
    </li>
  )
}

export default function TasksPage() {
  const clients = useClients()
  const team = useTeam()
  const [mine, setMine] = useState(false)
  const me = team.data?.me ?? undefined
  const filter = { done: false, assigneeId: mine ? me : undefined }
  const inFlow = useTeamStepTasks(filter)
  const names = Object.fromEntries((clients.data ?? []).map((c) => [c.id, c.name]))
  return (
    <div className="stack">
      <h1>Tasks</h1>
      <p className="help">To-dos for the team. Clients never see them.</p>
      <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} disabled={!me} /> Only mine</label>
      <h2>In onboardings</h2>
      <p className="help">Team tasks that are part of an onboarding's steps. Open one to work through it.</p>
      {inFlow.isError && <LoadError error={inFlow.error} what="onboarding tasks" />}
      {inFlow.isSuccess && inFlow.data.length === 0 && <Banner>No open team tasks in onboardings.</Banner>}
      <ul className="cards">{(inFlow.data ?? []).map((t) => <StepTaskRow key={`${t.onboarding_id}/${t.key}`} t={t} names={names} members={team.data?.members ?? []} />)}</ul>
      <h2>Other to-dos</h2>
      <p className="help">Not part of an onboarding, for example chasing an invoice.</p>
      <TasksPanel key={String(mine)} filter={filter} clientNames={names} showFinished={false} />
    </div>
  )
}
