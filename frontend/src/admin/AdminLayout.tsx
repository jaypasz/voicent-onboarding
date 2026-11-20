import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import { localMode } from '../auth/supabase'
import { Icon } from '../components/Icon'

const ITEMS = [
  { to: '/', label: 'Onboardings', icon: 'list', end: true },
  { to: '/new', label: 'New onboarding', icon: 'plus' },
  { to: '/clients', label: 'Clients', icon: 'users' },
  { to: '/templates', label: 'Templates', icon: 'layers' },
]

const KEY = 'vo.sidebar.collapsed'
// a remembered preference only; private windows and blocked storage just start expanded
const remembered = (): boolean => { try { return localStorage.getItem(KEY) === '1' } catch { return false } }
const remember = (v: boolean) => { try { localStorage.setItem(KEY, v ? '1' : '0') } catch { /* not kept, which is fine */ } }

export default function AdminLayout() {
  const { email, signOut } = useAuth()
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
    <div className={`admin-shell${collapsed ? ' is-collapsed' : ''}${open ? ' is-open' : ''}`}>
      <header className="topbar">
        <button type="button" className="btn btn-small" aria-expanded={open} aria-controls="admin-menu" onClick={() => setOpen(!open)}>
          <Icon name={open ? 'close' : 'menu'} /> Menu
        </button>
        <strong className="brand">Voicent Onboarding</strong>
      </header>
      <aside id="admin-menu" className="sidebar">
        <div className="sidebar-head">
          <strong className="brand"><span className="brand-mark" aria-hidden="true">VO</span><span className="nav-label">Voicent Onboarding</span></strong>
          <button type="button" className="sidebar-toggle" aria-expanded={!collapsed} aria-controls="admin-menu" onClick={toggle}
            aria-label={collapsed ? 'Expand the menu' : 'Collapse the menu'} title={collapsed ? 'Expand the menu' : 'Collapse the menu'}>
            <Icon name={collapsed ? 'expand' : 'collapse'} />
          </button>
          <button type="button" className="sidebar-close" onClick={() => setOpen(false)} aria-label="Close the menu">
            <Icon name="close" />
          </button>
        </div>
        <nav aria-label="Main">
          <ul>
            {ITEMS.map((i) => (
              <li key={i.to}>
                <NavLink to={i.to} end={i.end} title={collapsed ? i.label : undefined}>
                  <Icon name={i.icon} /><span className="nav-label">{i.label}</span>
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
