import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { checkTemplate, useCreateTemplate, useSaveTemplate, useTemplate, useTemplates } from '../api/admin'
import { ApiError } from '../api/http'
import StepsBuilder, { type BuilderValue } from '../builder/StepsBuilder'
import { clean, newStep, prepare, toSlug, type TemplateDoc } from '../builder/doc'
import { Banner, Problems } from '../components/Banner'
import { LoadError } from '../components/LoadError'

const BLANK: TemplateDoc = { name: '', slug: '', description: '', layout: 'checklist', nudge_after_days: 3, on_complete: 'none', sections: [], steps: [] }

type Settings = Omit<TemplateDoc, 'sections' | 'steps'>

/**
 * /templates/new                 a blank template
 * /templates/new?from=<id>       a copy of another template, under a new name
 * /templates/<id>/edit           change a template: saving adds a version, and onboardings already made keep theirs
 */
export default function TemplateBuilderPage() {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const from = params.get('from') ?? ''
  const sourceId = id || from
  const source = useTemplate(sourceId)
  const editing = !!id
  const templates = useTemplates(true) // archived ones too: a new template can't take their names
  const saveVersion = useSaveTemplate()
  const create = useCreateTemplate()
  const save = editing ? saveVersion : create
  const nav = useNavigate()
  const [settings, setSettings] = useState<Settings | null>(sourceId ? null : BLANK)
  const [value, setValue] = useState<BuilderValue>({ sections: [], steps: sourceId ? [] : prepare([newStep('form', [])]) })
  const [problems, setProblems] = useState<string[]>([])
  const [ok, setOk] = useState<string | null>(null)

  useEffect(() => {
    if (!source.data || settings) return
    const { sections, steps, ...rest } = source.data.document
    setSettings(editing ? rest : { ...rest, name: `${rest.name} (copy)`, slug: toSlug(`${rest.name} copy`) })
    setValue({ sections, steps: prepare(steps) })
  }, [source.data, settings, editing])

  if (sourceId && source.isError) return <div className="stack"><LoadError error={source.error} what="this template" /><Link to="/templates">← Templates</Link></div>
  if (!settings) return <p>Loading…</p>

  const slugTaken = !editing && !!settings.slug && !!templates.data?.some((t) => t.slug === settings.slug)
  const doc = (): TemplateDoc => {
    const { version: _v, ...rest } = settings
    return { ...rest, sections: value.sections, steps: clean(value.steps) }
  }
  const set = (patch: Partial<Settings>) => { setSettings({ ...settings, ...patch }); setOk(null) }
  const change = (v: BuilderValue) => { setValue(v); setOk(null) }

  async function check() {
    setProblems([])
    try {
      const r = await checkTemplate(doc())
      setProblems(r.problems)
      setOk(r.ok ? 'Everything checks out.' : null)
    } catch (e) {
      setProblems(e instanceof ApiError ? [e.message, ...e.problems] : ['That did not work.'])
    }
  }

  async function submit() {
    setProblems([])
    setOk(null)
    try {
      const t = await save.mutateAsync(doc())
      if (!editing) return nav(`/templates/${t.id}/edit`, { replace: true })
      setOk(t.new_version ? `Saved as version ${t.current_version}. Onboardings already made keep the version they started with.` : 'Nothing changed, so no new version was made.')
    } catch (e) {
      setProblems(e instanceof ApiError ? (e.problems.length ? e.problems : [e.message]) : ['That did not work.'])
    }
  }

  return (
    <div className="stack">
      <p><Link to="/templates">← Templates</Link></p>
      <h1>{editing ? `Edit “${source.data?.name}”` : from ? 'Copy a template' : 'New template'}</h1>
      {editing && <p className="help">Version {source.data?.current_version}. Saving makes a new version; clients already started keep theirs.</p>}

      <section className="card stack" aria-labelledby="tpl-settings-h">
        <h2 id="tpl-settings-h">About this template</h2>
        <div className="grid-2">
          <label className="field-group"><span>Name</span>
            <input value={settings.name} maxLength={200} required
              onChange={(e) => set(editing ? { name: e.target.value } : { name: e.target.value, slug: toSlug(e.target.value) })} />
          </label>
          <label className="field-group"><span>Short name (in links and exports)</span>
            <input value={settings.slug} maxLength={80} disabled={editing} aria-invalid={slugTaken || undefined} aria-describedby="slug-note"
              onChange={(e) => set({ slug: toSlug(e.target.value) })} />
            <span id="slug-note" className={slugTaken ? 'field-error' : 'help'}>
              {editing ? "Can't change once saved. Copy the template to use another one." : slugTaken ? 'Another template already uses this. Choose another.' : 'Lowercase letters, numbers and dashes.'}
            </span>
          </label>
        </div>
        <label className="field-group"><span>Description (optional)</span>
          <textarea rows={2} maxLength={1000} value={settings.description ?? ''} onChange={(e) => set({ description: e.target.value })} />
        </label>
        <fieldset className="checks">
          <legend>How the client sees it</legend>
          <div className="chips">
            <label className="check check-chip"><input type="radio" name="layout" checked={settings.layout === 'focus'} onChange={() => set({ layout: 'focus' })} /> One step per screen</label>
            <label className="check check-chip"><input type="radio" name="layout" checked={settings.layout === 'checklist'} onChange={() => set({ layout: 'checklist' })} /> A checklist</label>
          </div>
        </fieldset>
        <div className="grid-2">
          <label className="field-group"><span>Remind a quiet client after (days)</span>
            <input type="number" inputMode="numeric" min={1} max={30} value={settings.nudge_after_days ?? 3} onChange={(e) => set({ nudge_after_days: Math.trunc(Number(e.target.value)) || 3 })} />
          </label>
          <label className="check"><input type="checkbox" checked={settings.on_complete === 'provision_voicent_workspace'}
            onChange={(e) => set({ on_complete: e.target.checked ? 'provision_voicent_workspace' : 'none' })} /> When finished, ask Voicent-App to set up a workspace</label>
        </div>
      </section>

      <StepsBuilder value={value} onChange={change} />

      {problems.length > 0 && <Problems problems={problems} />}
      {ok && <Banner kind="ok">{ok}</Banner>}
      <div className="row wrap save-bar">
        <button type="button" className="btn" onClick={() => void check()}>Check it</button>
        <button type="button" className="btn btn-primary" disabled={save.isPending || slugTaken || !settings.name.trim() || !settings.slug || value.steps.length === 0} onClick={() => void submit()}>
          {save.isPending ? 'Saving…' : editing ? 'Save a new version' : 'Save template'}
        </button>
        {editing && <Link className="btn" to={`/templates/new?from=${id}`}>Save as a copy…</Link>}
      </div>
    </div>
  )
}
