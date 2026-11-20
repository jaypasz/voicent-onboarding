import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { useMe, useNotifications, useOrgSettings } from '../api/admin'
import { setAdminOrgGetter } from '../api/http'
import type { OrgChoice } from '../api/types'
import { LoadError } from '../components/LoadError'
import { brandStyle, safeLogo } from '../lib/brand'
import { useAuth } from '../auth/AuthContext'
import { localMode } from '../auth/supabase'
import { Icon } from '../components/Icon'

const ITEMS = [
  { to: '/', label: 'Onboardings', icon: 'list', end: true },
  { to: '/new', label: 'New onboarding', icon: 'plus' },
  { to: '/clients', label: 'Clients', icon: 'users' },
  { to: '/templates', label: 'Templates', icon: 'layers' },
  { to: '/notifications', label: 'Notifications', icon: 'bell' },
  { to: '/team', label: 'Team', icon: 'team' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
]

const ORG_KEY = 'vo.org'
const rememberedOrg = (): string | null => { try { return localStorage.getItem(ORG_KEY) } catch { return null } }
const rememberOrg = (id: string) => { try { localStorage.setItem(ORG_KEY, id) } catch { /* fine */ } }

const KEY = 'vo.sidebar.collapsed'
// a remembered preference only; private windows and blocked storage just start expanded
const remembered = (): boolean => { try { return localStorage.getItem(KEY) === '1' } catch { return false } }
const remember = (v: boolean) => { try { localStorage.setItem(KEY, v ? '1' : '0') } catch { /* not kept, which is fine */ } }

/** Picks the organization to work in before any page loads: the one a link names with ?org= (an email about an onboarding
 * names its org) when it is one of yours, else the remembered one, else the only one or the first. */
export default function AdminLayout() {
  const me = useMe()
  const qc = useQueryClient()
  const { search } = useLocation()
  const [chosen, setChosen] = useState<string | null>(() => new URLSearchParams(search).get('org') ?? rememberedOrg())
  const orgs = me.data?.orgs ?? []
  const org = orgs.find((o) => o.id === chosen) ?? orgs.find((o) => o.id === rememberedOrg()) ?? orgs[0] ?? null
  // every admin request from here on says which organization it is for
  setAdminOrgGetter(() => org?.id ?? null)
  // a linked org that turned out to be yours becomes the one remembered, as if picked from the menu
  useEffect(() => { if (org && org.id === chosen && chosen !== rememberedOrg()) rememberOrg(org.id) }, [org, chosen])

  if (me.isPending) return <main className="narrow"><p>Loading…</p></main>
  if (me.isError) return <main className="narrow stack"><LoadError error={me.error} what="your account" /></main>
  const choose = (id: string) => { rememberOrg(id); qc.clear(); setChosen(id) }
  return <Shell key={org?.id ?? 'none'} orgs={orgs} orgId={org?.id ?? null} onChoose={choose} />
}

function Shell({ orgs, orgId, onChoose }: { orgs: OrgChoice[]; orgId: string | null; onChoose: (id: string) => void }) {
  const { email, signOut } = useAuth()
  const settings = useOrgSettings(!!orgId)
  const unread = useNotifications().data?.unread ?? 0
  const brand = settings.data?.brand
  const logo = safeLogo(brand?.logo_url)
  useEffect(() => { document.title = brand?.name ? `${brand.name} · Onboarding` : 'Onboarding' }, [brand?.name])
  const [collapsed, setCollapsed] = useState(remembered)
  const [open, setOpen] = useState(false) // the phone-width drawer
  const location = useLocation()

  useEffect(() => setOpen(false), [location.pathname])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const toggle = () => { setCollapsed(!collapsed); remember(!collapsed) }
  return (
    <div className={`admin-shell${collapsed ? ' is-collapsed' : ''}${open ? ' is-open' : ''}`} style={brandStyle(brand)}>
      <header className="topbar">
        <button type="button" className="btn btn-small" aria-expanded={open} aria-controls="admin-menu" onClick={() => setOpen(!open)}>
          <Icon name={open ? 'close' : 'menu'} /> Menu
        </button>
        <strong className="brand">{brand?.name ?? 'Onboarding'}</strong>
      </header>
      <aside id="admin-menu" className="sidebar">
        <div className="sidebar-head">
          <strong className="brand">
            {logo ? <img src={logo} alt="" className="brand-logo" referrerPolicy="no-referrer" /> : <span className="brand-mark" aria-hidden="true">{initials(brand?.name)}</span>}
            <span className="nav-label">{brand?.name ?? 'Onboarding'}</span>
          </strong>
          <button type="button" className="sidebar-toggle" aria-expanded={!collapsed} aria-controls="admin-menu" onClick={toggle}
            aria-label={collapsed ? 'Expand the menu' : 'Collapse the menu'} title={collapsed ? 'Expand the menu' : 'Collapse the menu'}>
            <Icon name={collapsed ? 'expand' : 'collapse'} />
          </button>
          <button type="button" className="sidebar-close" onClick={() => setOpen(false)} aria-label="Close the menu">
            <Icon name="close" />
          </button>
        </div>
        {orgs.length > 1 && (
          <label className="field-group org-switch"><span className="nav-label">Organization</span>
            <select value={orgId ?? ''} onChange={(e) => onChoose(e.target.value)} aria-label="Organization">
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}{o.account_type === 'reseller' ? ' (reseller)' : ''}</option>)}
            </select>
          </label>
        )}
        <nav aria-label="Main">
          <ul>
            {ITEMS.map((i) => (
              <li key={i.to}>
                <NavLink to={i.to} end={i.end} title={collapsed ? i.label : undefined}>
                  <span className="nav-icon"><Icon name={i.icon} />{i.to === '/notifications' && unread > 0 && <span className="count" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}</span>
                  <span className="nav-label">{i.label}{i.to === '/notifications' && unread > 0 && <span className="sr-only">, {unread} new</span>}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="sidebar-foot">
          <span className="nav-label who">{email}</span>
          {!localMode && <button type="button" className="btn btn-small" onClick={() => void signOut()}><span className="nav-label">Sign out</span><span className="collapsed-only" aria-hidden="true">⎋</span></button>}
        </div>
      </aside>
      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden="true" />}
      <main className="admin-main">
        <Outlet />
      </main>
    </div>
  )
}

function initials(name?: string): string {
  const parts = (name || 'Onboarding').split(/\s+/).filter(Boolean)
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2)).toUpperCase()
}
