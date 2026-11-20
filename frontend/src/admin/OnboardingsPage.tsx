import { useState } from 'react'
import { Link } from 'react-router'
import { useClients, useOnboardings, useTeam } from '../api/admin'
import { memberLabel } from '../lib/team'
import type { OnboardingStatus } from '../api/types'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { OnboardingBadge } from '../components/StatusBadge'
import { ONBOARDING_STATUS, timeAgo } from '../lib/format'

const FILTERS: (OnboardingStatus | '')[] = ['', 'active', 'draft', 'paused', 'completed', 'archived']

export default function OnboardingsPage() {
  const [status, setStatus] = useState<OnboardingStatus | ''>('')
  const [mine, setMine] = useState(false)
  const list = useOnboardings(status, mine)
  const clients = useClients()
  const team = useTeam()
  const owner = (id?: string | null) => team.data?.members.find((m) => m.id === id)
  const name = (id: string) => clients.data?.find((c) => c.id === id)?.name ?? ''

  return (
    <div className="stack">
      <h1>Onboardings</h1>
      <div className="chips" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button key={f || 'all'} className={`chip${status === f ? ' chip-on' : ''}`} aria-pressed={status === f} onClick={() => setStatus(f)}>
            {f ? ONBOARDING_STATUS[f].label : 'All'}
          </button>
        ))}
      </div>
      <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Only the ones I look after</label>
      {list.isError && <LoadError error={list.error} what="onboardings" />}
      {list.isSuccess && list.data.length === 0 && (mine ? <Banner>You don't look after any onboardings{status ? ' with this status' : ''}.</Banner> : <Banner>Nothing here yet. <Link to="/new">Start an onboarding</Link>.</Banner>)}
      <ul className="cards">
        {list.data?.map((o) => (
          <li key={o.id} className="card">
            <Link to={`/onboardings/${o.id}`} className="card-link">
              <div className="row between">
                <strong>{o.title}</strong>
                <OnboardingBadge status={o.status} />
              </div>
              {o.attention && (
                <div><span className="badge badge-in_progress"><span aria-hidden="true">⚠</span> Needs you: {o.attention === 'unreachable' ? 'no way to reach them' : 'no reply to the reminders'}</span></div>
              )}
              {o.provision_state === 'failed' && (
                <div><span className="badge badge-in_progress"><span aria-hidden="true">⚠</span> Needs you: the Voicent workspace request didn't go through</span></div>
              )}
              <div className="help">
                {name(o.client_id)} · {o.progress.done} of {o.progress.total} steps done · active {timeAgo(o.last_activity_at)}
                {owner(o.owner_member_id) && ` · looked after by ${owner(o.owner_member_id)!.is_you ? 'you' : memberLabel(owner(o.owner_member_id))}`}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
