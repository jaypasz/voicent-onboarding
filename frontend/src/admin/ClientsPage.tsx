import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useClients, useCreateClient } from '../api/admin'
import { ApiError } from '../api/http'
import type { Client } from '../api/types'
import { Banner } from '../components/Banner'

const KINDS: Client['kind'][] = ['trades', 'agency', 'msp', 'other']

export default function ClientsPage() {
  const clients = useClients()
  const create = useCreateClient()
  const [name, setName] = useState('')
  const [kind, setKind] = useState<Client['kind']>('trades')
  const [error, setError] = useState<string | null>(null)

  async function add(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await create.mutateAsync({ name: name.trim(), kind })
      setName('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That did not work.')
    }
  }

  return (
    <div className="stack">
      <h1>Clients</h1>
      <form onSubmit={add} className="row wrap" aria-label="Add a client">
        <label className="field-group grow"><span>Business name</span><input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label className="field-group"><span>Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as Client['kind'])}>{KINDS.map((k) => <option key={k}>{k}</option>)}</select>
        </label>
        <button className="btn btn-primary" disabled={create.isPending || !name.trim()}>Add client</button>
      </form>
      {error && <Banner kind="error">{error}</Banner>}
      {clients.data?.length === 0 && <Banner>No clients yet.</Banner>}
      <ul className="cards">
        {clients.data?.map((c) => (
          <li key={c.id} className="card">
            <Link to={`/clients/${c.id}`} className="card-link">
              <div className="row between"><strong>{c.name}</strong><span className="help">{c.kind}{c.status === 'archived' ? ' · archived' : ''}</span></div>
              <div className="help">{c.contacts.length} contact{c.contacts.length === 1 ? '' : 's'}</div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
