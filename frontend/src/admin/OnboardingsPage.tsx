import { useState } from 'react'
import { Link } from 'react-router'
import { useClients, useOnboardings } from '../api/admin'
import type { OnboardingStatus } from '../api/types'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { OnboardingBadge } from '../components/StatusBadge'
import { ONBOARDING_STATUS, timeAgo } from '../lib/format'

const FILTERS: (OnboardingStatus | '')[] = ['', 'active', 'draft', 'paused', 'completed', 'archived']

export default function OnboardingsPage() {
  const [status, setStatus] = useState<OnboardingStatus | ''>('')
  const list = useOnboardings(status)
  const clients = useClients()
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
      {list.isError && <LoadError error={list.error} what="onboardings" />}
      {list.isSuccess && list.data.length === 0 && <Banner>Nothing here yet. <Link to="/new">Start an onboarding</Link>.</Banner>}
      <ul className="cards">
        {list.data?.map((o) => (
          <li key={o.id} className="card">
            <Link to={`/onboardings/${o.id}`} className="card-link">
              <div className="row between">
                <strong>{o.title}</strong>
                <OnboardingBadge status={o.status} />
              </div>
              <div className="help">
                {name(o.client_id)} · {o.progress.done} of {o.progress.total} steps done · active {timeAgo(o.last_activity_at)}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
