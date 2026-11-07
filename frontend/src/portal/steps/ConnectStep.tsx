import { useState } from 'react'
import { safeHttpsUrl } from '../../lib/links'
import { Problems } from '../../components/Banner'
import type { StepProps } from './types'

export default function ConnectStep({ step, submit, busy, problems }: StepProps) {
  const [label, setLabel] = useState<string>(step.response?.account_label ?? '')
  const [missing, setMissing] = useState(false)
  const start = safeHttpsUrl(step.config.start_url)

  async function done() {
    if (!label.trim()) return setMissing(true)
    setMissing(false)
    await submit({ status: 'connected', account_label: label.trim() }).catch(() => {})
  }

  return (
    <div className="stack">
      <p>
        <strong>{step.config.label}</strong>
      </p>
      {step.config.instructions && <p>{step.config.instructions}</p>}
      <p className="help">Please don't send passwords or access keys. Delegated access or an invitation is safer.</p>
      {start && (
        <a className="btn" href={start} target="_blank" rel="noopener noreferrer">
          Open {step.config.label} ↗
        </a>
      )}
      <Problems problems={problems} />
      {step.can_write && (
        <>
          <label className="field-group">
            <span>Which account is it?</span>
            <input value={label} onChange={(e) => setLabel(e.target.value)} disabled={busy} aria-invalid={missing || undefined} aria-describedby={missing ? 'connect-err' : undefined} />
          </label>
          {missing && (
            <div id="connect-err" className="field-error" role="alert">
              <span aria-hidden="true">✕</span> Say which account it is.
            </div>
          )}
          <button className="btn btn-primary btn-big" disabled={busy} onClick={done}>
            {busy ? 'Saving…' : "I've done this"}
          </button>
          <button className="btn btn-big" disabled={busy} onClick={() => void submit({ status: 'pending' }).catch(() => {})}>
            I need a hand with this
          </button>
        </>
      )}
      {step.response && (
        <p className="help">
          {step.response.status === 'connected' ? `Connected: ${step.response.account_label}` : 'You asked for help with this. We will be in touch.'}
        </p>
      )}
    </div>
  )
}
