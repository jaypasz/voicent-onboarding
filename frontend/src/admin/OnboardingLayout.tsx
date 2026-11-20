import { Link, NavLink, Outlet, useParams } from 'react-router'
import { useClients, useOnboarding } from '../api/admin'
import { LoadError } from '../components/LoadError'
import { OnboardingBadge } from '../components/StatusBadge'

/** One onboarding: its title and status, then tabs. Each tab is its own address, so it can be linked to and reloaded. */
export default function OnboardingLayout() {
  const { id = '' } = useParams()
  const ob = useOnboarding(id)
  const clients = useClients()
  if (ob.isPending) return <p>Loading…</p>
  if (ob.isError || !ob.data) return <div className="stack"><LoadError error={ob.error} what="this onboarding" /><Link to="/">← Onboardings</Link></div>
  const o = ob.data
  const client = clients.data?.find((c) => c.id === o.client_id)
  const tabs = [
    { to: `/onboardings/${id}`, label: 'Overview', end: true },
    { to: `/onboardings/${id}/steps`, label: o.status === 'draft' ? 'Edit steps' : 'Steps' },
    { to: `/onboardings/${id}/preview`, label: 'Client preview' },
    { to: `/onboardings/${id}/follow-up`, label: 'Links & follow-up' },
  ]
  return (
    <div className="stack">
      <p><Link to="/">← Onboardings</Link></p>
      <div className="row between wrap">
        <div>
          <h1>{o.title}</h1>
          <p className="help">{client ? <Link to={`/clients/${client.id}`}>{client.name}</Link> : null} · {o.layout === 'focus' ? 'one step per screen' : 'checklist'}</p>
        </div>
        <OnboardingBadge status={o.status} />
      </div>
      <nav className="tabs" aria-label="This onboarding">
        {tabs.map((t) => <NavLink key={t.to} to={t.to} end={t.end} className="tab">{t.label}</NavLink>)}
      </nav>
      <Outlet />
    </div>
  )
}
