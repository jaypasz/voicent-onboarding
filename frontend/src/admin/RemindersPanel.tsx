import { useEffect, useState } from 'react'
import { useFeatures, useNudgeHistory, usePauseReminders, useRemindNow } from '../api/admin'
import { ApiError } from '../api/http'
import type { NudgeResult, NudgeRow, OnboardingDetail } from '../api/types'
import { Banner } from '../components/Banner'
import { formatDateTime } from '../lib/format'

// Colour never carries meaning alone: every outcome has a glyph and a word.
const OUTCOME: Record<string, { glyph: string; label: string }> = {
  sent: { glyph: '✓', label: 'Sent' },
  failed: { glyph: '✕', label: 'Failed' },
  later: { glyph: '◐', label: 'Will try later' },
  skipped: { glyph: '–', label: "Couldn't send" },
  queued: { glyph: '◐', label: 'Not finished' },
  would_send: { glyph: '○', label: 'Would send' },
}
const CHANNEL: Record<string, string> = { sms: 'text message', email: 'email' }

function Result({ r }: { r: NudgeResult }) {
  const o = OUTCOME[r.status] ?? OUTCOME.skipped
  return (
    <div>
      <span className="badge"><span aria-hidden="true">{o.glyph}</span> {o.label}</span> <strong>{r.contact}</strong>
      {r.channel ? ` by ${CHANNEL[r.channel]}` : ''}
      {r.reason ? <span className="help"> · {r.reason}</span> : null}
    </div>
  )
}

function HistoryRow({ n }: { n: NudgeRow }) {
  const o = OUTCOME[n.status] ?? OUTCOME.queued
  return (
    <div>
      <span className="badge"><span aria-hidden="true">{o.glyph}</span> {o.label}</span> {n.contact} by {CHANNEL[n.channel]}
      <span className="help"> · {n.kind === 'manual' ? 'sent by you' : 'automatic'} · {formatDateTime(n.at)}{n.error ? ` · ${n.error}` : ''}</span>
    </div>
  )
}

export default function RemindersPanel({ ob }: { ob: OnboardingDetail }) {
  const features = useFeatures()
  const history = useNudgeHistory(ob.id)
  const remind = useRemindNow(ob.id)
  const pause = usePauseReminders(ob.id)
  const [results, setResults] = useState<{ results: NudgeResult[]; message: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  // The switch answers at once and puts itself back, with a message, if the save fails.
  const [paused, setPaused] = useState(ob.nudges_paused)
  useEffect(() => setPaused(ob.nudges_paused), [ob.nudges_paused])
  const on = features.data?.reminders === true

  function togglePaused(value: boolean) {
    setPaused(value)
    setError(null)
    pause.mutate(value, {
      onError: (e) => {
        setPaused(!value)
        setError(e instanceof ApiError ? e.message : "That didn't save. Try again.")
      },
    })
  }

  async function send() {
    setError(null)
    setResults(null)
    try {
      setResults(await remind.mutateAsync())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.')
    }
  }

  return (
    <section className="stack" aria-labelledby="reminders-h">
      <h2 id="reminders-h">Reminders</h2>
      {features.isSuccess && !on && (
        <Banner kind="warn">
          Reminders are off. The server needs <code>APP_URL</code> and either Twilio (texts) or Resend (email) settings. See DEPLOY.md.
        </Banner>
      )}
      {on && (
        <p className="help">
          If a client goes quiet, they're reminded on their own: by text if they agreed to texts, otherwise by email, never at night where they are,
          and no more than a few times. {features.data!.sms ? '' : 'Texts are off. '}{features.data!.email ? '' : 'Email is off. '}
        </p>
      )}
      {error && <Banner kind="error">{error}</Banner>}
      <div className="row wrap">
        <button className="btn" disabled={!on || ob.status !== 'active' || remind.isPending} onClick={() => void send()}>
          {remind.isPending ? 'Sending…' : 'Send a reminder now'}
        </button>
        <label className="check">
          <input type="checkbox" checked={paused} onChange={(e) => togglePaused(e.target.checked)} /> Don't remind this client automatically
        </label>
      </div>
      {ob.status !== 'active' && on && <p className="help">Reminders only go to active onboardings.</p>}
      {results && (results.results.length ? <ul className="cards" aria-label="Result">{results.results.map((r) => <li key={r.contact} className="card"><Result r={r} /></li>)}</ul> : <Banner>{results.message}</Banner>)}
      {history.data && history.data.length > 0 && (
        <>
          <h3>Sent so far</h3>
          <ul className="cards" aria-label="Reminder history">{history.data.map((n) => <li key={n.id} className="card"><HistoryRow n={n} /></li>)}</ul>
        </>
      )}
    </section>
  )
}
