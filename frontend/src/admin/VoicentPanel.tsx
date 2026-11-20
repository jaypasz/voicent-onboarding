import { useState } from 'react'
import { useProvisionNow, useProvisionStatus } from '../api/admin'
import { ApiError } from '../api/http'
import type { OnboardingDetail, ProvisionStatus } from '../api/types'
import { Banner } from '../components/Banner'
import { formatDateTime } from '../lib/format'

type Shown = Exclude<ProvisionStatus['state'], 'not_wanted'>

const STATE: Record<Shown, { glyph: string; label: string; badge: string; text: (s: ProvisionStatus) => string }> = {
  waiting: { glyph: '○', label: 'Not yet', badge: '', text: () => 'When the client has finished every step, Voicent-App is asked to set up their workspace.' },
  pending: {
    glyph: '◐', label: 'On its way', badge: '',
    text: (s) => (s.attempts === 0 ? 'Going to Voicent-App in the background within a few minutes.' : `Not through yet. It tries again by itself${s.next_attempt_at ? ` at ${formatDateTime(s.next_attempt_at)}` : ''}.`),
  },
  delivered: {
    glyph: '✓', label: 'Requested', badge: 'badge-done',
    text: (s) => `Voicent-App accepted the request${s.delivered_at ? ` on ${formatDateTime(s.delivered_at)}` : ''}${s.workspace_id ? ` (workspace ${s.workspace_id})` : ''}.`,
  },
  failed: { glyph: '✕', label: "Didn't go through", badge: 'badge-in_progress', text: () => "Voicent-App didn't take the request, and it won't be tried again by itself. The reason is below." },
  off: { glyph: '–', label: 'Switched off', badge: '', text: () => 'The server needs VOICENT_PROVISION_URL and VOICENT_PROVISION_SECRET to ask Voicent-App for a workspace. See DEPLOY.md.' },
}

/** Shown only for onboardings whose template sets up a Voicent workspace when it is finished. */
export default function VoicentPanel({ ob }: { ob: OnboardingDetail }) {
  const status = useProvisionStatus(ob.id)
  const send = useProvisionNow(ob.id)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const s = status.data
  if (s && !s.wanted) return null

  async function run() {
    setError(null)
    setMessage(null)
    try {
      const r = await send.mutateAsync()
      if (r.result) setMessage({ ok: r.result.ok, text: r.result.message })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.')
    }
  }

  const info = s && s.state !== 'not_wanted' ? STATE[s.state] : null
  const canSend = s?.enabled && ob.status === 'completed' && s.state !== 'waiting'
  return (
    <section className="stack" aria-labelledby="voicent-h">
      <h2 id="voicent-h">Voicent workspace</h2>
      {status.isError && <Banner kind="error">Couldn't check the Voicent workspace request.</Banner>}
      {s && info && (
        <p>
          <span className={`badge ${info.badge}`}><span aria-hidden="true">{info.glyph}</span> {info.label}</span> {info.text(s)}
        </p>
      )}
      {s?.error && s.state !== 'delivered' && <p className="help">Last problem: {s.error}</p>}
      {error && <Banner kind="error">{error}</Banner>}
      {message && <Banner kind={message.ok ? 'ok' : 'error'}>{message.text}</Banner>}
      {canSend && (
        <div className="row">
          <button className="btn" disabled={send.isPending} onClick={() => void run()}>
            {send.isPending ? 'Sending…' : s.state === 'delivered' ? 'Send again with the latest answers' : 'Send to Voicent-App now'}
          </button>
        </div>
      )}
      {s && s.log.length > 0 && (
        <ul className="cards" aria-label="Recent workspace requests">
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
