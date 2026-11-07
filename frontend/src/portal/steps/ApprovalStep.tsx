import { useState } from 'react'
import { safeHttpsUrl } from '../../lib/links'
import { Problems } from '../../components/Banner'
import type { StepProps } from './types'

export default function ApprovalStep({ step, submit, busy, problems }: StepProps) {
  const [asking, setAsking] = useState(false)
  const [comment, setComment] = useState('')
  const [missing, setMissing] = useState(false)
  const d = step.config.deliverable ?? {}
  const link = d.kind === 'link' ? safeHttpsUrl(d.url) : null
  const last = step.response as { decision?: string; comment?: string } | null

  async function requestChanges() {
    if (!comment.trim()) return setMissing(true)
    setMissing(false)
    await submit({ decision: 'changes_requested', comment: comment.trim() }).catch(() => {})
    setAsking(false)
    setComment('')
  }

  return (
    <div className="stack">
      {step.config.prompt && <p>{step.config.prompt}</p>}
      <div className="deliverable">
        {d.kind === 'text' && <blockquote>{d.text}</blockquote>}
        {d.kind === 'link' &&
          (link ? (
            <a className="btn" href={link} target="_blank" rel="noopener noreferrer">
              Open to review ↗
            </a>
          ) : (
            <span className="help">The review link isn't available.</span>
          ))}
        {d.kind === 'file' && <p>File to review: {d.file_name}</p>}
      </div>
      <Problems problems={problems} />
      {last?.decision && (
        <p className="help">
          {last.decision === 'approved' ? '✓ You approved this.' : `◐ You asked for changes: "${last.comment}". We'll send a new version.`}
        </p>
      )}
      {step.can_write && (
        <>
          {!asking ? (
            <>
              <button className="btn btn-primary btn-big" disabled={busy} onClick={() => void submit({ decision: 'approved' }).catch(() => {})}>
                {busy ? 'Saving…' : 'Approve'}
              </button>
              <button className="btn btn-big" disabled={busy} onClick={() => setAsking(true)}>
                Ask for changes
              </button>
            </>
          ) : (
            <>
              <label className="field-group">
                <span>What should change?</span>
                <textarea rows={4} value={comment} onChange={(e) => setComment(e.target.value)} aria-invalid={missing || undefined} />
              </label>
              {missing && (
                <div className="field-error" role="alert">
                  <span aria-hidden="true">✕</span> Say what should change.
                </div>
              )}
              <button className="btn btn-primary btn-big" disabled={busy} onClick={requestChanges}>
                Send
              </button>
              <button className="btn btn-big" onClick={() => setAsking(false)}>
                Cancel
              </button>
            </>
          )}
        </>
      )}
    </div>
  )
}
