import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { useOnboardingDocument, useSaveOnboardingSteps } from '../api/admin'
import { ApiError } from '../api/http'
import SaveAsTemplate from '../builder/SaveAsTemplate'
import StepsBuilder, { type BuilderValue } from '../builder/StepsBuilder'
import { clean, kindOf, prepare } from '../builder/doc'
import { Banner, Problems } from '../components/Banner'
import { LoadError } from '../components/LoadError'

/** One client's steps. A draft can be changed freely; after sending, the steps can only be saved as a template. */
export default function OnboardingStepsPage() {
  const { id = '' } = useParams()
  const doc = useOnboardingDocument(id)
  const save = useSaveOnboardingSteps(id)
  const [value, setValue] = useState<BuilderValue | null>(null)
  const [dirty, setDirty] = useState(false)
  const [problems, setProblems] = useState<string[]>([])
  const [ok, setOk] = useState(false)

  useEffect(() => {
    if (doc.data && !value) setValue({ sections: doc.data.document.sections, steps: prepare(doc.data.document.steps) })
  }, [doc.data, value])

  if (doc.isError) return <LoadError error={doc.error} what="this onboarding's steps" />
  if (!doc.data || !value) return <p>Loading…</p>
  const d = doc.data

  async function submit() {
    setProblems([])
    setOk(false)
    try {
      const r = await save.mutateAsync({ sections: value!.sections, steps: clean(value!.steps) })
      setValue({ sections: r.document.sections, steps: prepare(r.document.steps) })
      setDirty(false)
      setOk(true)
    } catch (e) {
      setProblems(e instanceof ApiError ? [e.message, ...e.problems] : ['That did not work.'])
    }
  }

  return (
    <div className="stack">
      {d.editable ? (
        <>
          <p className="help">These changes are for this client only. The template “{d.document.name}” stays as it is.</p>
          <StepsBuilder value={value} onChange={(v) => { setValue(v); setDirty(true); setOk(false) }} locked={d.locked} />
          {problems.length > 0 && <Problems problems={problems} />}
          {ok && <Banner kind="ok">Saved. The client sees these steps when you send the onboarding.</Banner>}
          <div className="row wrap save-bar">
            <button type="button" className="btn btn-primary" disabled={!dirty || save.isPending || value.steps.length === 0} onClick={() => void submit()}>
              {save.isPending ? 'Saving…' : 'Save steps'}
            </button>
            {dirty && <span className="help">Not saved yet.</span>}
          </div>
        </>
      ) : (
        <>
          <Banner>This onboarding has been sent, so its steps can't change any more. You can still keep them as a template.</Banner>
          <ol className="cards step-preview">
            {value.steps.map((s) => <li key={s._uid} className="card"><strong>{s.title}</strong> <span className="help">· {kindOf(s.type)?.label ?? s.type}</span></li>)}
          </ol>
        </>
      )}
      <SaveAsTemplate base={d.document} value={value} />
    </div>
  )
}
