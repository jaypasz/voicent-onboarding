import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useClients, useCreateClient } from '../api/admin'
import { ApiError } from '../api/http'
import type { Client, Stage } from '../api/types'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { StageBadge } from '../components/StageBadge'
import { STAGE, STAGES } from '../lib/format'

const KINDS: Client['kind'][] = ['trades', 'agency', 'msp', 'other']

export default function ClientsPage() {
  const clients = useClients()
  const create = useCreateClient()
  const [name, setName] = useState('')
  const [kind, setKind] = useState<Client['kind']>('trades')
  const [error, setError] = useState<string | null>(null)
  const [stage, setStage] = useState<Stage | ''>('')

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

  const shown = (clients.data ?? []).filter((c) => !stage || c.stage === stage)

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
      {clients.isSuccess && (
        <div className="row wrap" role="group" aria-label="Show clients by stage">
          {(['', ...STAGES] as const).map((st) => {
            const n = st ? clients.data.filter((c) => c.stage === st).length : clients.data.length
            return (
              <button key={st || 'all'} type="button" className={`btn btn-small${stage === st ? ' btn-primary' : ''}`} aria-pressed={stage === st} onClick={() => setStage(st)}>
                {st ? STAGE[st].label : 'All'} ({n})
              </button>
            )
          })}
        </div>
      )}
      {clients.isError && <LoadError error={clients.error} what="clients" />}
      {clients.isSuccess && clients.data.length === 0 && <Banner>No clients yet.</Banner>}
      {clients.isSuccess && clients.data.length > 0 && shown.length === 0 && <Banner>No clients are {STAGE[stage as Stage].label.toLowerCase()}.</Banner>}
      <ul className="cards">
        {shown.map((c) => (
          <li key={c.id} className="card">
            <Link to={`/clients/${c.id}`} className="card-link">
              <div className="row between"><strong>{c.name}</strong><span className="row"><StageBadge stage={c.stage} /><span className="help">{c.kind}{c.status === 'archived' ? ' · archived' : ''}</span></span></div>
              <div className="help">{c.contacts.length} contact{c.contacts.length === 1 ? '' : 's'}</div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
