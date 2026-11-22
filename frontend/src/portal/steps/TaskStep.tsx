import { useState } from 'react'
import { Problems } from '../../components/Banner'
import type { StepProps } from './types'

/** A task for the client: instructions, a checklist they tick (saved as they go), and a button when it has no checklist. */
export default function TaskStep({ step, submit, busy, problems }: StepProps) {
  const items: string[] = step.config.checklist ?? []
  const saved = (step.response?.checked as number[] | undefined) ?? []
  const [note, setNote] = useState((step.response?.note as string | undefined) ?? '')
  const done = step.status === 'done'

  const tick = (i: number, on: boolean) => {
    const checked = on ? [...new Set([...saved, i])] : saved.filter((x) => x !== i)
    return submit({ checked, ...(note.trim() ? { note: note.trim() } : {}) }).catch(() => {})
  }

  return (
    <div className="stack">
      {step.config.instructions && <p style={{ whiteSpace: 'pre-wrap' }}>{step.config.instructions}</p>}
      {items.length > 0 && (
        <ul className="checklist" aria-label="Checklist">
          {items.map((c, i) => (
            <li key={c}>
              <label className="check">
                <input type="checkbox" checked={saved.includes(i)} disabled={!step.can_write || busy} onChange={(e) => void tick(i, e.target.checked)} /> <span>{c}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <Problems problems={problems} />
      {step.can_write && (
        <>
          <label className="field-group">
            <span>Note for us (optional)</span>
            <textarea rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} />
          </label>
          {items.length === 0 && !done && (
            <button className="btn btn-primary btn-big" disabled={busy} onClick={() => void submit({ done: true, ...(note.trim() ? { note: note.trim() } : {}) }).catch(() => {})}>
              {busy ? 'Saving…' : 'Mark as done'}
            </button>
          )}
          {items.length === 0 && done && (
            <button className="btn btn-big" disabled={busy} onClick={() => void submit({ done: false, ...(note.trim() ? { note: note.trim() } : {}) }).catch(() => {})}>Not done after all</button>
          )}
          {items.length > 0 && !done && saved.length > 0 && note.trim() !== (step.response?.note ?? '') && (
            <button className="btn" disabled={busy} onClick={() => void submit({ checked: saved, note: note.trim() }).catch(() => {})}>Save note</button>
          )}
        </>
      )}
      {done && <p className="help">✓ Done. Thank you.</p>}
    </div>
  )
}
