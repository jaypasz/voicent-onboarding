import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/http'
import type { Comment } from '../api/types'
import { Banner } from '../components/Banner'
import { timeAgo } from '../lib/format'
import { usePortal } from './session'

export default function Comments({ stepKey, comments, canWrite, onChanged }: { stepKey: string; comments: Comment[]; canWrite: boolean; onChanged: () => Promise<unknown> }) {
  const { call } = usePortal()
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function send(e: FormEvent) {
    e.preventDefault()
    if (!body.trim()) return
    setBusy(true)
    setError(null)
    try {
      await call(`/portal/steps/${stepKey}/comments`, { body: { body: body.trim() } })
      setBody('')
      await onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The comment did not send.')
    } finally {
      setBusy(false)
    }
  }

  if (!comments.length && !canWrite) return null
  return (
    <section className="comments" aria-label="Comments">
      {comments.length > 0 && (
        <ul>
          {comments.map((c) => (
            <li key={c.id} className={`comment comment-${c.author_kind}`}>
              <div className="comment-meta">
                {c.author_kind === 'admin' ? 'Voicent' : c.author_label} · {timeAgo(c.created_at)}
              </div>
              <div>{c.body}</div>
            </li>
          ))}
        </ul>
      )}
      {canWrite &&
        (open ? (
          <form onSubmit={send} className="stack">
            {error && <Banner kind="error">{error}</Banner>}
            <label className="field-group">
              <span>Your message</span>
              <textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} />
            </label>
            <div className="row">
              <button className="btn btn-primary" disabled={busy || !body.trim()}>
                {busy ? 'Sending…' : 'Send'}
              </button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <button type="button" className="btn btn-link" onClick={() => setOpen(true)}>
            Ask a question or leave a note
          </button>
        ))}
    </section>
  )
}
