import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { useClients, useCreateOnboarding, useTemplates } from '../api/admin'
import { ApiError } from '../api/http'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'

export default function NewOnboardingPage() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const clients = useClients()
  const templates = useTemplates()
  const create = useCreateOnboarding()
  const [clientId, setClientId] = useState(params.get('client') ?? '')
  const [templateId, setTemplateId] = useState('')
  const [title, setTitle] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      const ob = await create.mutateAsync({ client_id: clientId, template_id: templateId, title: title.trim() || undefined })
      nav(`/onboardings/${ob.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That did not work.')
    }
  }

  const noClients = clients.isSuccess && clients.data.length === 0
  const noTemplates = templates.isSuccess && templates.data.length === 0
  return (
    <form onSubmit={submit} className="stack narrow-form">
      <h1>New onboarding</h1>
      {error && <Banner kind="error">{error}</Banner>}
      {clients.isError && <LoadError error={clients.error} what="clients" />}
      {templates.isError && <LoadError error={templates.error} what="templates" />}
      {noClients && <Banner>Add a client first. <Link to="/clients">Clients</Link></Banner>}
      {noTemplates && <Banner>No templates yet. <Link to="/templates">Install the presets</Link></Banner>}
      <label className="field-group">
        <span>Client</span>
        <select value={clientId} onChange={(e) => setClientId(e.target.value)} required>
          <option value="">Choose…</option>
          {clients.data?.filter((c) => c.status === 'active').map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <label className="field-group">
        <span>Template</span>
        <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} required>
          <option value="">Choose…</option>
          {templates.data?.map((t) => <option key={t.id} value={t.id}>{t.name} (v{t.current_version})</option>)}
        </select>
      </label>
      <label className="field-group">
        <span>Title (optional)</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Defaults to the template and client name" />
      </label>
      <p className="help">This creates a draft. Nothing is sent to the client until you press Send on the next page.</p>
      <button className="btn btn-primary" disabled={create.isPending || !clientId || !templateId}>{create.isPending ? 'Creating…' : 'Create draft'}</button>
    </form>
  )
}
