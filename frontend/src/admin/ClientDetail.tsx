import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { useAddContact, useClients, useOnboardings, useSetOutcome, useSetPaying, useUpdateClient, useUpdateContact } from '../api/admin'
import { STAGE, formatDateTime } from '../lib/format'
import { ApiError } from '../api/http'
import type { Client, Contact } from '../api/types'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { StageBadge } from '../components/StageBadge'
import { OnboardingBadge } from '../components/StatusBadge'
import { TasksPanel } from './TasksPanel'

function ContactRow({ clientId, c }: { clientId: string; c: Contact }) {
  const update = useUpdateContact(clientId)
  const [error, setError] = useState<string | null>(null)
  async function toggleConsent() {
    setError(null)
    try {
      const source = c.sms_consent ? '' : (window.prompt('Where did this person agree to text messages? (e.g. "signed form 2026-11-01")') ?? '')
      if (!c.sms_consent && !source.trim()) return
      await update.mutateAsync({ id: c.id, patch: { sms_consent: !c.sms_consent, sms_consent_source: source || c.sms_consent_source } })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.')
    }
  }
  return (
    <li className="card">
      <div className="row between wrap">
        <div><strong>{c.name}</strong> {c.role && <span className="help">· {c.role}</span>}</div>
        <button className="btn btn-small" onClick={toggleConsent}>{c.sms_consent ? '✓ Texts allowed. Withdraw' : 'Record text consent'}</button>
      </div>
      <div className="help">{[c.email, c.phone].filter(Boolean).join(' · ') || 'No email or phone yet'}{c.sms_consent && c.sms_consent_source ? ` · consent: ${c.sms_consent_source}` : ''}</div>
      {error && <Banner kind="error">{error}</Banner>}
    </li>
  )
}

/** Paying is what lets a finished onboarding set up the client's Voicent workspace. Until then they are a lead. */
function PayingCard({ clientId, since }: { clientId: string; since: string | null }) {
  const set = useSetPaying(clientId)
  const [error, setError] = useState<string | null>(null)
  async function toggle() {
    const q = since
      ? 'Mark this client as not paying? A Voicent workspace request still waiting is cancelled; one already set up stays.'
      : 'Mark this client as a paying customer? Any finished onboarding of theirs that sets up a Voicent workspace is sent then.'
    if (!window.confirm(q)) return
    setError(null)
    try {
      await set.mutateAsync(!since)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.')
    }
  }
  return (
    <section className="card row between wrap" aria-label="Paying customer">
      <div>
        <span className={`badge ${since ? 'badge-done' : ''}`}><span aria-hidden="true">{since ? '✓' : '○'}</span> {since ? 'Paying customer' : 'Not paying yet (a lead)'}</span>
        <p className="help">{since ? `Since ${formatDateTime(since)}. Their Voicent workspace can be set up.` : 'No Voicent workspace is set up until they pay.'}</p>
      </div>
      <button className={`btn btn-small${since ? '' : ' btn-primary'}`} disabled={set.isPending} onClick={() => void toggle()}>{since ? 'Mark as not paying' : 'Mark as paying'}</button>
      {error && <Banner kind="error">{error}</Banner>}
    </section>
  )
}

/** Where they are in the pipeline. Lead, onboarding and won follow from what exists; lost and stalled are your call. */
function StageCard({ client }: { client: Client }) {
  const set = useSetOutcome(client.id)
  const [error, setError] = useState<string | null>(null)
  async function go(outcome: 'lost' | 'stalled' | null) {
    setError(null)
    try { await set.mutateAsync(outcome) } catch (e) { setError(e instanceof ApiError ? e.message : 'That did not work.') }
  }
  return (
    <section className="card row between wrap" aria-label="Stage">
      <div>
        <StageBadge stage={client.stage} />
        <p className="help">{STAGE[client.stage].help}</p>
      </div>
      <div className="row wrap">
        {client.outcome
          ? <button className="btn btn-small" disabled={set.isPending} onClick={() => void go(null)}>Reopen</button>
          : !client.paying_since && <>
              <button className="btn btn-small" disabled={set.isPending} onClick={() => void go('stalled')}>Mark stalled</button>
              <button className="btn btn-small" disabled={set.isPending} onClick={() => void go('lost')}>Mark lost</button>
            </>}
      </div>
      {error && <Banner kind="error">{error}</Banner>}
    </section>
  )
}

export default function ClientDetail() {
  const { id = '' } = useParams()
  const clients = useClients()
  const client = clients.data?.find((c) => c.id === id)
  const onboardings = useOnboardings()
  const update = useUpdateClient(id)
  const add = useAddContact(id)
  const [f, setF] = useState({ name: '', email: '', phone: '', role: '' })
  const [error, setError] = useState<string | null>(null)

  if (clients.isPending) return <p>Loading…</p>
  if (clients.isError) return <LoadError error={clients.error} what="this client" />
  if (!client) return <Banner kind="error">Client not found. <Link to="/clients">Back to clients</Link></Banner>

  async function addContact(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await add.mutateAsync({ name: f.name.trim(), email: f.email, phone: f.phone, role: f.role })
      setF({ name: '', email: '', phone: '', role: '' })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That did not work.')
    }
  }

  const zones = ['America/New_York', 'America/Chicago', 'America/Denver', 'America/Phoenix', 'America/Los_Angeles', 'America/Anchorage', 'Pacific/Honolulu', 'Europe/London', 'Europe/Paris', 'Asia/Tokyo', 'Australia/Sydney']
  if (!zones.includes(client.timezone)) zones.push(client.timezone)
  const mine = onboardings.data?.filter((o) => o.client_id === id) ?? []
  return (
    <div className="stack">
      <p><Link to="/clients">← Clients</Link></p>
      <div className="row between wrap">
        <h1>{client.name}</h1>
        <button className="btn btn-small" onClick={() => update.mutate({ status: client.status === 'active' ? 'archived' : 'active' })}>
          {client.status === 'active' ? 'Archive client' : 'Restore client'}
        </button>
      </div>
      <p className="help">{client.kind}{client.status === 'archived' ? ' · archived' : ''}</p>
      <StageCard client={client} />
      <PayingCard clientId={client.id} since={client.paying_since} />
      <label className="field-group narrow-form">
        <span>Their time zone</span>
        <select value={client.timezone} onChange={(e) => update.mutate({ timezone: e.target.value })}>
          {zones.map((z) => <option key={z} value={z}>{z.replace(/_/g, ' ')}</option>)}
        </select>
        <span className="help">Reminders are never sent at night here (9pm to 8am their time).</span>
      </label>

      <h2>Contacts</h2>
      <p className="help">The role matches steps in a template. A step for "owner" goes to the contact whose role is "owner".</p>
      <ul className="cards">{client.contacts.map((c) => <ContactRow key={c.id} clientId={id} c={c} />)}</ul>
      <form onSubmit={addContact} className="row wrap" aria-label="Add a contact">
        <label className="field-group grow"><span>Name</span><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></label>
        <label className="field-group"><span>Role</span><input value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} placeholder="owner, it, billing" /></label>
        <label className="field-group"><span>Email</span><input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        <label className="field-group"><span>Phone</span><input type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></label>
        <button className="btn btn-primary" disabled={add.isPending || !f.name.trim()}>Add contact</button>
      </form>
      {error && <Banner kind="error">{error}</Banner>}

      <h2>Tasks</h2>
      <TasksPanel filter={{ clientId: id }} clientId={id} />

      <div className="row between wrap">
        <h2>Onboardings</h2>
        <Link className="btn btn-small" to={`/new?client=${id}`}>New onboarding</Link>
      </div>
      {mine.length === 0 ? <p className="help">None yet.</p> : (
        <ul className="cards">{mine.map((o) => (
          <li key={o.id} className="card"><Link to={`/onboardings/${o.id}`} className="card-link"><div className="row between"><strong>{o.title}</strong><OnboardingBadge status={o.status} /></div></Link></li>
        ))}</ul>
      )}
    </div>
  )
}
