import { useState } from 'react'
import { useFeatures, useSyncNow, useSyncStatus } from '../api/admin'
import { ApiError } from '../api/http'
import type { OnboardingDetail, SyncState } from '../api/types'
import { Banner } from '../components/Banner'
import { formatDateTime } from '../lib/format'

const STATE: Record<SyncState['state'], { glyph: string; label: string; text: string }> = {
  synced: { glyph: '✓', label: 'Up to date', text: 'Your AIOS board has this onboarding as a project, with a task for each step.' },
  pending: { glyph: '◐', label: 'Waiting to sync', text: "A change hasn't reached AIOS yet. It goes in the background within a few minutes." },
  failing: { glyph: '✕', label: "Isn't syncing", text: "The last attempt to update AIOS failed. It tries again by itself; the reason is below." },
  not_sent: { glyph: '○', label: 'Not started', text: 'Nothing goes to AIOS until you send this to the client.' },
  off: { glyph: '–', label: 'Switched off', text: 'The server needs AIOS_API_URL and AIOS_SERVICE_TOKEN to keep your AIOS board up to date. See DEPLOY.md.' },
}

export default function AiosPanel({ ob }: { ob: OnboardingDetail }) {
  const features = useFeatures()
  const status = useSyncStatus(ob.id)
  const sync = useSyncNow(ob.id)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  if (features.isSuccess && !features.data.aios_sync && status.data?.state === 'off' && ob.status === 'draft') return null // nothing to say yet

  async function run() {
    setError(null)
    setMessage(null)
    try {
      const r = await sync.mutateAsync()
      if (r.result) setMessage({ ok: r.result.ok, text: r.result.message })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.')
    }
  }

  const s = status.data
  const info = s ? STATE[s.state] : null
  return (
    <section className="stack" aria-labelledby="aios-h">
      <h2 id="aios-h">AIOS board</h2>
      {status.isError && <Banner kind="error">Couldn't check the AIOS sync.</Banner>}
      {info && (
        <p>
          <span className={`badge ${s!.state === 'synced' ? 'badge-done' : s!.state === 'failing' ? 'badge-in_progress' : ''}`}><span aria-hidden="true">{info.glyph}</span> {info.label}</span>{' '}
          {info.text}
        </p>
      )}
      {error && <Banner kind="error">{error}</Banner>}
      {message && <Banner kind={message.ok ? 'ok' : 'error'}>{message.text}</Banner>}
      {s?.enabled && (
        <div className="row">
          <button className="btn" disabled={ob.status === 'draft' || sync.isPending} onClick={() => void run()}>{sync.isPending ? 'Syncing…' : 'Sync now'}</button>
        </div>
      )}
      {s && s.log.length > 0 && (
        <ul className="cards" aria-label="Recent sync activity">
          {s.log.map((l, i) => (
            <li key={`${l.at}-${i}`} className="card help">
              <span aria-hidden="true">{l.status === 'ok' ? '✓' : '✕'}</span> {l.status === 'ok' ? 'Worked' : 'Failed'} · {formatDateTime(l.at)} · {l.detail}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
