import { NavLink, Outlet } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import { localMode } from '../auth/supabase'

export default function AdminLayout() {
  const { email, signOut } = useAuth()
  return (
    <>
      <header className="admin-bar">
        <strong className="brand">Voicent Onboarding</strong>
        <nav aria-label="Main">
          <NavLink to="/" end>Onboardings</NavLink>
          <NavLink to="/clients">Clients</NavLink>
          <NavLink to="/templates">Templates</NavLink>
          <NavLink to="/new" className="btn btn-primary btn-small">New onboarding</NavLink>
        </nav>
        <span className="who">
          {email}
          {!localMode && <button className="btn btn-small" onClick={() => void signOut()}>Sign out</button>}
        </span>
      </header>
      <main className="admin-main">
        <Outlet />
      </main>
    </>
  )
}
