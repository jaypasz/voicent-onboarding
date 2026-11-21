import { useState } from 'react'
import { useClients, useTeam } from '../api/admin'

import { TasksPanel } from './TasksPanel'

export default function TasksPage() {
  const clients = useClients()
  const team = useTeam()
  const [mine, setMine] = useState(false)
  const me = team.data?.me ?? undefined
  const names = Object.fromEntries((clients.data ?? []).map((c) => [c.id, c.name]))
  return (
    <div className="stack">
      <h1>Tasks</h1>
      <p className="help">To-dos for the team. Clients never see them.</p>
      <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} disabled={!me} /> Only mine</label>
      <TasksPanel key={String(mine)} filter={{ done: false, assigneeId: mine ? me : undefined }} clientNames={names} showFinished={false} />
    </div>
  )
}
