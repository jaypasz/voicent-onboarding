import { useState } from 'react'
import { fetchFileUrl } from '../api/admin'
import { ApiError } from '../api/http'
import type { AdminStep, FormField } from '../api/types'
import { formatBytes, formatDateTime } from '../lib/format'

function FileLink({ onboardingId, id, name, size }: { onboardingId: string; id: string; name: string; size: number }) {
  const [error, setError] = useState<string | null>(null)
  async function open() {
    setError(null)
    try {
      const r = await fetchFileUrl(onboardingId, id)
      window.open(r.url, '_blank', 'noopener,noreferrer')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't get the file.")
    }
  }
  return (
    <li>
      {name} <span className="help">({formatBytes(size)})</span> <button className="btn btn-small" onClick={open}>Download</button>
      {error && <span className="field-error"> ✕ {error}</span>}
    </li>
  )
}

/** What the client (or Jay) answered, in words. Never raw JSON. */
export default function StepResponse({ onboardingId, step }: { onboardingId: string; step: AdminStep }) {
  const r = step.response
  if (!r) return <p className="help">No answer yet.</p>
  const d = r.data
  const who = <p className="help">Answered {formatDateTime(r.submitted_at)} by {r.submitted_by.startsWith('contact:') ? 'the client' : r.submitted_by.replace('admin:', '')}{step.revisions > 1 ? ` · version ${r.revision} of ${step.revisions}` : ''}</p>
  switch (step.type) {
    case 'form': {
      const fields = (step.config.fields ?? []) as FormField[]
      return (
        <>
          <dl className="answers">
            {fields.filter((f) => d.answers?.[f.key] !== undefined).map((f) => {
              const v = d.answers[f.key]
              return (<div key={f.key}><dt>{f.label}</dt><dd>{Array.isArray(v) ? v.join(', ') : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : String(v)}</dd></div>)
            })}
          </dl>
          {who}
        </>
      )
    }
    case 'upload':
      return (
        <>
          <ul className="files">{step.files.filter((f) => (d.file_ids ?? []).includes(f.id)).map((f) => <FileLink key={f.id} onboardingId={onboardingId} id={f.id} name={f.name} size={f.size} />)}</ul>
          {(d.file_ids ?? []).length === 0 && <p>Nothing to upload.</p>}
          {who}
        </>
      )
    case 'connect':
      return <><p>{d.status === 'connected' ? `✓ Connected: ${d.account_label}` : '◐ The client asked for help.'}</p>{who}</>
    case 'book_call':
      return <><p>{d.booked ? `✓ Booked${d.when ? `: ${formatDateTime(d.when)}` : ''}` : 'Not booked yet.'}</p>{who}</>
    case 'approval':
      return <><p>{d.decision === 'approved' ? '✓ Approved' : `◐ Changes requested: "${d.comment}"`}</p>{who}</>
    case 'internal_task':
      return <>{d.note ? <p>{d.note}</p> : <p className="help">Done, no note.</p>}{who}</>
    default:
      return <p className="help">An answer is recorded for this step.</p>
  }
}
