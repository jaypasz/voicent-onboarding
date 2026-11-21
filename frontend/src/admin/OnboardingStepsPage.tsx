import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { useOnboardingDocument, useSaveOnboardingSteps } from '../api/admin'
import { ApiError } from '../api/http'
import SaveAsTemplate from '../builder/SaveAsTemplate'
import StepsBuilder, { type BuilderValue } from '../builder/StepsBuilder'
import { clean, kindOf, prepare } from '../builder/doc'
import { Banner, Problems } from '../components/Banner'
import { LoadError } from '../components/LoadError'

/** One client's steps. Editable before and after sending (not once archived); after sending, a save is live for the client at once. */
export default function OnboardingStepsPage() {
  const { id = '' } = useParams()
  const doc = useOnboardingDocument(id)
  const save = useSaveOnboardingSteps(id)
  const [value, setValue] = useState<BuilderValue | null>(null)
  const [dirty, setDirty] = useState(false)
  const [problems, setProblems] = useState<string[]>([])
  const [ok, setOk] = useState(false)
  const [etag, setEtag] = useState<string | undefined>(undefined)
  const [stale, setStale] = useState(false)

  useEffect(() => {
    if (doc.data && !value) { setValue({ sections: doc.data.document.sections, steps: prepare(doc.data.document.steps) }); setEtag(doc.data.etag); setStale(false) }
  }, [doc.data, value])

  if (doc.isError) return <LoadError error={doc.error} what="this onboarding's steps" />
  if (!doc.data || !value) return <p>Loading…</p>
  const d = doc.data

  async function submit() {
    if (d.sent && !window.confirm('This onboarding has been sent. Save these changes? The client sees them straight away.')) return
    setProblems([])
    setOk(false)
    setStale(false)
    try {
      const r = await save.mutateAsync({ sections: value!.sections, steps: clean(value!.steps), etag })
      setValue({ sections: r.document.sections, steps: prepare(r.document.steps) })
      setEtag(r.etag)
      setDirty(false)
      setOk(true)
    } catch (e) {
      setProblems(e instanceof ApiError ? [e.message, ...e.problems] : ['That did not work.'])
      setStale(e instanceof ApiError && e.status === 409 && e.problems.length === 0)
    }
  }

  async function reload() {
    const r = await doc.refetch() // wait for the fresh copy: resetting from the cached one would bring the stale steps back
    if (!r.data) return
    setValue({ sections: r.data.document.sections, steps: prepare(r.data.document.steps) })
    setEtag(r.data.etag)
    setDirty(false)
    setProblems([])
    setStale(false)
  }

  return (
    <div className="stack">
      {d.editable ? (
        <>
          <p className="help">These changes are for this client only. The template “{d.document.name}” stays as it is.</p>
          {d.sent && <Banner kind="warn">This onboarding has been sent, so the client sees saved changes straight away. A step that already has answers, files or comments can be edited but not removed: skip it instead.</Banner>}
          <StepsBuilder value={value} onChange={(v) => { setValue(v); setDirty(true); setOk(false) }} locked={d.locked} />
          {problems.length > 0 && <Problems problems={problems} />}
          {stale && <button type="button" className="btn btn-small" onClick={() => void reload()}>Reload the latest steps</button>}
          {ok && <Banner kind="ok">{d.sent ? 'Saved. The client sees these changes now.' : 'Saved. The client sees these steps when you send the onboarding.'}</Banner>}
          <div className="row wrap save-bar">
            <button type="button" className="btn btn-primary" disabled={!dirty || save.isPending || value.steps.length === 0} onClick={() => void submit()}>
              {save.isPending ? 'Saving…' : d.sent ? 'Save changes' : 'Save steps'}
            </button>
            {dirty && <span className="help">Not saved yet.</span>}
          </div>
        </>
      ) : (
        <>
          <Banner>This onboarding is archived, so its steps can't change. You can still keep them as a template.</Banner>
          <ol className="cards step-preview">
            {value.steps.map((s) => <li key={s._uid} className="card"><strong>{s.title}</strong> <span className="help">· {kindOf(s.type)?.label ?? s.type}</span></li>)}
          </ol>
        </>
      )}
      <SaveAsTemplate base={d.document} value={value} />
    </div>
  )
}
