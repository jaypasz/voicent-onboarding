import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { useClients, useCreateOnboarding, useTemplate, useTemplates } from '../api/admin'
import { ApiError } from '../api/http'
import SaveAsTemplate from '../builder/SaveAsTemplate'
import StepsBuilder, { type BuilderValue } from '../builder/StepsBuilder'
import { clean, kindOf, prepare } from '../builder/doc'
import { Banner, Problems } from '../components/Banner'
import { LoadError } from '../components/LoadError'

export default function NewOnboardingPage() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const clients = useClients()
  const templates = useTemplates()
  const create = useCreateOnboarding()
  const [clientId, setClientId] = useState(params.get('client') ?? '')
  const [templateId, setTemplateId] = useState('')
  const template = useTemplate(templateId)
  const [title, setTitle] = useState('')
  // the customised copy, made from the chosen template the first time "Customize" is ticked
  const [custom, setCustom] = useState<BuilderValue | null>(null)
  const [problems, setProblems] = useState<string[]>([])

  function chooseTemplate(id: string) {
    if (custom && !window.confirm('Choosing another template throws away your changes to these steps. Go ahead?')) return
    setTemplateId(id)
    setCustom(null)
  }

  function toggleCustom(on: boolean) {
    if (!on && custom && !window.confirm('Use the template as it is and throw away your changes?')) return
    const doc = template.data?.document
    setCustom(on && doc ? { sections: doc.sections, steps: prepare(doc.steps) } : null)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setProblems([])
    try {
      const ob = await create.mutateAsync({
        client_id: clientId, template_id: templateId, title: title.trim() || undefined,
        ...(custom ? { sections: custom.sections, steps: clean(custom.steps) } : {}),
      })
      nav(`/onboardings/${ob.id}`)
    } catch (err) {
      setProblems(err instanceof ApiError ? [err.message, ...err.problems] : ['That did not work.'])
    }
  }

  const noClients = clients.isSuccess && clients.data.length === 0
  const noTemplates = templates.isSuccess && templates.data.length === 0
  const doc = template.data?.document
  return (
    <form onSubmit={submit} className="stack">
      <h1>New onboarding</h1>
      {clients.isError && <LoadError error={clients.error} what="clients" />}
      {templates.isError && <LoadError error={templates.error} what="templates" />}
      {noClients && <Banner>Add a client first. <Link to="/clients">Clients</Link></Banner>}
      {noTemplates && <Banner>No templates yet. <Link to="/templates">Install the presets</Link> or <Link to="/templates/new">build one</Link>.</Banner>}
      <div className="stack narrow-form">
        <label className="field-group">
          <span>Client</span>
          <select value={clientId} onChange={(e) => setClientId(e.target.value)} required>
            <option value="">Choose…</option>
            {clients.data?.filter((c) => c.status === 'active').map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="field-group">
          <span>Template</span>
          <select value={templateId} onChange={(e) => chooseTemplate(e.target.value)} required>
            <option value="">Choose…</option>
            {templates.data?.map((t) => <option key={t.id} value={t.id}>{t.name} (v{t.current_version})</option>)}
          </select>
        </label>
        <label className="field-group">
          <span>Title (optional)</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Defaults to the template and client name" />
        </label>
      </div>

      {templateId && template.isError && <LoadError error={template.error} what="this template" />}
      {doc && (
        <section className="stack" aria-labelledby="steps-h">
          <h2 id="steps-h">Steps</h2>
          <label className="check"><input type="checkbox" checked={!!custom} onChange={(e) => toggleCustom(e.target.checked)} /> Customize the steps for this client</label>
          {custom ? (
            <>
              <p className="help">Changes here are for this client only. “{doc.name}” itself stays as it is, unless you save these steps as a new template.</p>
              <StepsBuilder value={custom} onChange={setCustom} />
              <SaveAsTemplate base={doc} value={custom} />
            </>
          ) : (
            <ol className="cards step-preview">
              {doc.steps.map((s) => (
                <li key={s.key} className="card"><strong>{s.title}</strong> <span className="help">· {kindOf(s.type)?.label ?? s.type}</span></li>
              ))}
            </ol>
          )}
        </section>
      )}

      {problems.length > 0 && <Problems problems={problems} />}
      <p className="help">This creates a draft. Nothing is sent to the client until you press Send on the next page, and you can still change the steps until then.</p>
      <div className="row save-bar">
        <button className="btn btn-primary" disabled={create.isPending || !clientId || !templateId || (custom?.steps.length === 0)}>{create.isPending ? 'Creating…' : 'Create draft'}</button>
      </div>
    </form>
  )
}
