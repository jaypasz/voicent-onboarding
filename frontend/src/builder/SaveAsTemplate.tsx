import { useState } from 'react'
import { Link } from 'react-router'
import { useSaveTemplate, useTemplates } from '../api/admin'
import { ApiError } from '../api/http'
import type { TemplateDetail } from '../api/types'
import { Banner, Problems } from '../components/Banner'
import type { BuilderValue } from './StepsBuilder'
import { clean, toSlug, type TemplateDoc } from './doc'

/** Saves these steps as a brand-new template. It never adds a version to an existing one: a taken name is refused here. */
export default function SaveAsTemplate({ base, value }: { base: TemplateDoc; value: BuilderValue }) {
  const templates = useTemplates()
  const save = useSaveTemplate()
  const [name, setName] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const [saved, setSaved] = useState<TemplateDetail | null>(null)
  const slug = toSlug(name)
  const taken = !!slug && !!templates.data?.some((t) => t.slug === slug)

  async function run() {
    setProblems([])
    setSaved(null)
    const { version: _v, ...rest } = base
    try {
      setSaved(await save.mutateAsync({ ...rest, name: name.trim(), slug, sections: value.sections, steps: clean(value.steps) }))
      setName('')
    } catch (e) {
      setProblems(e instanceof ApiError ? (e.problems.length ? e.problems : [e.message]) : ['That did not work.'])
    }
  }

  return (
    <section className="card stack" aria-labelledby="save-tpl-h">
      <h3 id="save-tpl-h">Save as a template</h3>
      <p className="help">Keep these steps to use with other clients. This makes a new template; the one you started from doesn't change.</p>
      <div className="row wrap">
        <label className="field-group grow"><span>Template name</span>
          <input value={name} maxLength={200} onChange={(e) => { setName(e.target.value); setSaved(null) }} placeholder={`${base.name} (custom)`} aria-invalid={taken || undefined} aria-describedby="save-tpl-note" />
        </label>
        <button type="button" className="btn" disabled={!slug || taken || save.isPending || templates.isPending} onClick={() => void run()}>
          {save.isPending ? 'Saving…' : 'Save as template'}
        </button>
      </div>
      <p id="save-tpl-note" className={taken ? 'field-error' : 'help'}>
        {taken ? 'A template with this name already exists. Choose another name.' : slug ? `Saved as “${slug}”.` : 'Give it a name first.'}
      </p>
      {problems.length > 0 && <Problems problems={problems} />}
      {saved && <Banner kind="ok">Saved “{saved.name}”. <Link to={`/templates/${saved.id}/edit`}>Open it</Link></Banner>}
    </section>
  )
}
