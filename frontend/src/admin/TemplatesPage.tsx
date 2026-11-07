import { useState } from 'react'
import { fetchTemplateYaml, useImportYaml, useInstallPresets, useTemplates } from '../api/admin'
import { ApiError } from '../api/http'
import type { YamlImportResult } from '../api/types'
import { Banner, Problems } from '../components/Banner'

export default function TemplatesPage() {
  const templates = useTemplates()
  const presets = useInstallPresets()
  const importer = useImportYaml()
  const [yaml, setYaml] = useState('')
  const [result, setResult] = useState<YamlImportResult | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function run(dry_run: boolean) {
    setMessage(null)
    try {
      const r = await importer.mutateAsync({ yaml, dry_run })
      setResult(r)
      if (!dry_run) setMessage(r.new_version ? 'Saved as a new version.' : 'Nothing changed, so no new version was made.')
    } catch (e) {
      setResult({ ok: false, problems: e instanceof ApiError ? (e.problems.length ? e.problems : [e.message]) : ['That did not work.'] })
    }
  }

  async function download(id: string, slug: string) {
    const text = await fetchTemplateYaml(id)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/yaml' }))
    a.download = `${slug}.yaml`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="stack">
      <div className="row between wrap">
        <h1>Templates</h1>
        <button className="btn" disabled={presets.isPending} onClick={() => presets.mutate()}>Install the preset templates</button>
      </div>
      {presets.data && <Banner kind="ok">{presets.data.added.length ? `Added: ${presets.data.added.join(', ')}.` : 'All the presets are already here.'}</Banner>}
      {templates.data?.length === 0 && <Banner>No templates yet. Install the presets, or paste your own YAML below.</Banner>}
      <ul className="cards">
        {templates.data?.map((t) => (
          <li key={t.id} className="card row between wrap">
            <div><strong>{t.name}</strong> <span className="help">· {t.slug} · version {t.current_version}</span></div>
            <button className="btn btn-small" onClick={() => void download(t.id, t.slug)}>Download YAML</button>
          </li>
        ))}
      </ul>

      <h2>Import YAML</h2>
      <p className="help">A template with a slug that already exists becomes a new version. Onboardings already started keep the version they began with.</p>
      <label className="field-group"><span>Template YAML</span>
        <textarea className="mono" rows={12} value={yaml} onChange={(e) => { setYaml(e.target.value); setResult(null) }} spellCheck={false} />
      </label>
      <div className="row">
        <button className="btn" disabled={!yaml.trim() || importer.isPending} onClick={() => void run(true)}>Check it</button>
        <button className="btn btn-primary" disabled={!yaml.trim() || importer.isPending} onClick={() => void run(false)}>Save</button>
      </div>
      {result && !result.ok && <Problems problems={result.problems} />}
      {result?.ok && !message && <Banner kind="ok">This template is valid.</Banner>}
      {message && <Banner kind="ok">{message}</Banner>}
    </div>
  )
}
