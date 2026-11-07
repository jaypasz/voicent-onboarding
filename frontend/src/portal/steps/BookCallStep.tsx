import { useState } from 'react'
import { safeHttpsUrl } from '../../lib/links'
import { formatDateTime } from '../../lib/format'
import { Problems } from '../../components/Banner'
import type { StepProps } from './types'

export default function BookCallStep({ step, submit, busy, problems }: StepProps) {
  const [when, setWhen] = useState('')
  const url = safeHttpsUrl(step.config.url)
  const booked = step.response?.booked === true

  return (
    <div className="stack">
      {step.config.instructions && <p>{step.config.instructions}</p>}
      {step.config.duration_minutes && <p className="help">About {step.config.duration_minutes} minutes.</p>}
      {url ? (
        <a className="btn btn-primary btn-big" href={url} target="_blank" rel="noopener noreferrer">
          Pick a time ↗
        </a>
      ) : (
        <p className="help">The booking link isn't available. Tell us a time that suits you in the comments.</p>
      )}
      <Problems problems={problems} />
      {step.can_write && (
        <>
          <label className="field-group">
            <span>When is it? (optional)</span>
            <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} disabled={busy} />
          </label>
          <button className="btn btn-big" disabled={busy} onClick={() => void submit({ booked: true, ...(when ? { when } : {}) }).catch(() => {})}>
            {busy ? 'Saving…' : "I've booked it"}
          </button>
        </>
      )}
      {booked && <p className="help">Booked{step.response?.when ? `: ${formatDateTime(step.response.when)}` : ''}.</p>}
    </div>
  )
}
