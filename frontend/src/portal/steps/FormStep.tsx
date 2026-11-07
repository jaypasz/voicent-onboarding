import { useState, type FormEvent } from 'react'
import type { FormField } from '../../api/types'
import { problemsByField } from '../../lib/problems'
import { Problems } from '../../components/Banner'
import type { StepProps } from './types'

type Value = string | boolean | string[]

function initial(fields: FormField[], saved: Record<string, any> | undefined): Record<string, Value> {
  const out: Record<string, Value> = {}
  for (const f of fields) {
    const v = saved?.[f.key]
    out[f.key] = f.type === 'checkbox' ? v === true : f.type === 'multiselect' ? (Array.isArray(v) ? v : []) : typeof v === 'string' ? v : ''
  }
  return out
}

export default function FormStep({ step, submit, busy, problems }: StepProps) {
  const fields = (step.config.fields ?? []) as FormField[]
  const [values, setValues] = useState(() => initial(fields, step.response?.answers))
  const [local, setLocal] = useState<Record<string, string>>({})
  const readOnly = !step.can_write
  const { byKey, rest } = problemsByField(problems, fields)
  const shown = { ...byKey, ...local }

  function set(key: string, v: Value) {
    setValues((s) => ({ ...s, [key]: v }))
    setLocal((s) => {
      const { [key]: _gone, ...others } = s
      return others
    })
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const missing: Record<string, string> = {}
    for (const f of fields) {
      const v = values[f.key]
      const empty = f.type === 'checkbox' ? v !== true : Array.isArray(v) ? v.length === 0 : String(v).trim() === ''
      if (f.required && empty) missing[f.key] = f.type === 'checkbox' ? 'This needs to be ticked.' : 'This is required.'
    }
    setLocal(missing)
    if (Object.keys(missing).length) return
    const answers: Record<string, Value> = {}
    for (const f of fields) {
      const v = values[f.key]
      if (f.type === 'checkbox') answers[f.key] = v === true
      else if (Array.isArray(v) ? v.length : String(v).trim()) answers[f.key] = Array.isArray(v) ? v : String(v).trim()
    }
    await submit({ answers }).catch(() => {})
  }

  return (
    <form onSubmit={onSubmit} className="stack" noValidate>
      {step.config.intro && <p>{step.config.intro}</p>}
      <Problems problems={rest} />
      {fields.map((f) => {
        const id = `f-${step.key}-${f.key}`
        const err = shown[f.key]
        const label = (
          <span>
            {f.label}
            {f.required ? <span className="req"> (required)</span> : null}
          </span>
        )
        const common = { id, disabled: readOnly || busy, 'aria-invalid': err ? true : undefined, 'aria-describedby': err ? `${id}-err` : f.help ? `${id}-help` : undefined }
        let control
        if (f.type === 'textarea') control = <textarea {...common} rows={4} value={values[f.key] as string} onChange={(e) => set(f.key, e.target.value)} />
        else if (f.type === 'select')
          control = (
            <select {...common} value={values[f.key] as string} onChange={(e) => set(f.key, e.target.value)}>
              <option value="">Choose…</option>
              {(f.options ?? []).map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          )
        else if (f.type === 'multiselect')
          control = (
            <fieldset className="checks" disabled={readOnly || busy} aria-describedby={common['aria-describedby']}>
              <legend>{label}</legend>
              {(f.options ?? []).map((o) => (
                <label key={o} className="check">
                  <input
                    type="checkbox"
                    checked={(values[f.key] as string[]).includes(o)}
                    onChange={(e) => set(f.key, e.target.checked ? [...(values[f.key] as string[]), o] : (values[f.key] as string[]).filter((x) => x !== o))}
                  />{' '}
                  {o}
                </label>
              ))}
            </fieldset>
          )
        else if (f.type === 'checkbox')
          control = (
            <label className="check">
              <input {...common} type="checkbox" checked={values[f.key] === true} onChange={(e) => set(f.key, e.target.checked)} /> {label}
            </label>
          )
        else {
          const type = { phone: 'tel', email: 'email', url: 'url', date: 'date' }[f.type as string] ?? 'text'
          control = <input {...common} type={type} inputMode={f.type === 'phone' ? 'tel' : undefined} autoComplete={f.type === 'email' ? 'email' : f.type === 'phone' ? 'tel' : 'off'} value={values[f.key] as string} onChange={(e) => set(f.key, e.target.value)} />
        }
        const labelled = f.type === 'multiselect' || f.type === 'checkbox' ? control : (
          <label className="field" htmlFor={id}>
            {label}
          </label>
        )
        return (
          <div key={f.key} className="field-group">
            {labelled}
            {f.type !== 'multiselect' && f.type !== 'checkbox' ? control : null}
            {f.help && !err ? (
              <div id={`${id}-help`} className="help">
                {f.help}
              </div>
            ) : null}
            {err ? (
              <div id={`${id}-err`} className="field-error" role="alert">
                <span aria-hidden="true">✕</span> {err}
              </div>
            ) : null}
          </div>
        )
      })}
      {!readOnly && (
        <button className="btn btn-primary btn-big" disabled={busy}>
          {busy ? 'Saving…' : step.status === 'done' ? 'Save changes' : 'Save and continue'}
        </button>
      )}
    </form>
  )
}
