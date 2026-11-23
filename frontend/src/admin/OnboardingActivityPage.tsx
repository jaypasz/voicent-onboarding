import { useState } from 'react'
import { useParams } from 'react-router'
import { useActivity } from '../api/admin'
import type { AuditEntry } from '../api/types'
import { LoadError } from '../components/LoadError'

const WHO: Record<AuditEntry['actor_kind'], { glyph: string; word: string }> = {
  team: { glyph: '●', word: 'Team' },
  client: { glyph: '◆', word: 'Client' },
  system: { glyph: '⚙', word: 'System' },
}

const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', second: '2-digit' })

/** The audit trail of one onboarding: every change, by whom and when, newest first, grouped by day. */
export default function OnboardingActivityPage() {
  const { id = '' } = useParams()
  const q = useActivity(id)
  const [who, setWho] = useState<'' | AuditEntry['actor_kind']>('')
  if (q.isPending) return <p>Loading…</p>
  if (q.isError) return <LoadError error={q.error} what="this onboarding's activity" />
  const all = q.data.pages.flat()
  const rows = who ? all.filter((r) => r.actor_kind === who) : all
  const days: [string, AuditEntry[]][] = []
  for (const r of rows) {
    const d = day(r.at)
    if (days.at(-1)?.[0] === d) days.at(-1)![1].push(r)
    else days.push([d, [r]])
  }
  return (
    <section className="stack" aria-labelledby="activity-h">
      <div className="row between wrap">
        <div>
          <h2 id="activity-h">Activity</h2>
          <p className="help">Every change to this onboarding and its client, by whom and when. Entries can't be edited or deleted. What a client wrote is never shown here.</p>
        </div>
        <label className="field-group activity-filter">
          <span>Show</span>
          <select value={who} onChange={(e) => setWho(e.target.value as typeof who)}>
            <option value="">Everyone</option>
            <option value="team">Our team</option>
            <option value="client">The client</option>
            <option value="system">The system (reminders, notices, Voicent-App)</option>
          </select>
        </label>
      </div>
      {rows.length === 0 && <p className="help">{all.length ? 'Nothing from them in what is loaded.' : 'Nothing recorded yet.'}</p>}
      {days.map(([d, items]) => (
        <section key={d} className="activity-day" aria-label={d}>
          <h3>{d}</h3>
          <ol className="activity">
            {items.map((r) => (
              <li key={r.id} className={`activity-item activity-${r.actor_kind}`}>
                <time dateTime={r.at}>{time(r.at)}</time>
                <span className="activity-who"><span aria-hidden="true">{WHO[r.actor_kind].glyph}</span> {r.actor_label} <span className="help">({WHO[r.actor_kind].word.toLowerCase()})</span></span>
                <span className="activity-what">{r.summary}{r.about_client && <span className="badge">Client record</span>}</span>
              </li>
            ))}
          </ol>
        </section>
      ))}
      {q.hasNextPage && (
        <button type="button" className="btn" disabled={q.isFetchingNextPage} onClick={() => void q.fetchNextPage()}>
          {q.isFetchingNextPage ? 'Loading…' : 'Show older'}
        </button>
      )}
    </section>
  )
}
