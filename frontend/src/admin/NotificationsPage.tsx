import { Link } from 'react-router'
import { useMarkRead, useNotifications } from '../api/admin'
import { LoadError } from '../components/LoadError'
import { formatDateTime } from '../lib/format'

/** What happened that you should know about: things given to you, clients answering, onboardings finishing or going quiet. */
export default function NotificationsPage() {
  const list = useNotifications()
  const read = useMarkRead()
  if (list.isError) return <LoadError error={list.error} what="your notifications" />
  if (!list.data) return <p>Loading…</p>
  const { items, unread } = list.data
  return (
    <div className="stack">
      <div className="row between wrap">
        <h1>Notifications</h1>
        {unread > 0 && <button className="btn btn-small" disabled={read.isPending} onClick={() => read.mutate(undefined)}>Mark all as read</button>}
      </div>
      {items.length === 0 && <p className="help">Nothing yet. You'll see things here when you're given an onboarding or a step, and when clients answer.</p>}
      <ul className="cards" aria-label="Notifications">
        {items.map((n) => (
          <li key={n.id} className={`card notification${n.read ? '' : ' is-unread'}`}>
            <span className="badge"><span aria-hidden="true">{n.read ? '○' : '●'}</span> {n.read ? 'Read' : 'New'}</span>{' '}
            {n.onboarding_id
              ? <Link to={`/onboardings/${n.onboarding_id}`} onClick={() => !n.read && read.mutate([n.id])}>{n.text}</Link>
              : <span>{n.text}</span>}
            <div className="help">{formatDateTime(n.created_at)}</div>
          </li>
        ))}
      </ul>
    </div>
  )
}
