import { useId, useState } from 'react'
import { FIELD_TYPES, UPLOAD_EXTENSIONS, move, toKey, uid, uniqueKey, type FieldDoc, type FieldType } from './doc'

type Config = Record<string, any>
interface Props {
  config: Config
  onChange: (c: Config) => void
}

/** Sets a key, or removes it when the value is empty, so optional settings don't fail the server's checks. */
function put(config: Config, key: string, value: unknown): Config {
  const out = { ...config }
  if (value === '' || value === undefined || value === null || (Array.isArray(value) && value.length === 0 && key !== 'fields' && key !== 'accept')) delete out[key]
  else out[key] = value
  return out
}

const num = (v: string): number | undefined => (v.trim() === '' ? undefined : Math.trunc(Number(v)))
const lines = (v: string): string[] => v.split('\n').map((l) => l.trim()).filter(Boolean)

function Text({ label, value, onChange, area, type = 'text', help, placeholder }: {
  label: string; value: string | undefined; onChange: (v: string) => void; area?: boolean; type?: string; help?: string; placeholder?: string
}) {
  const id = useId()
  return (
    <label className="field-group" htmlFor={id}>
      <span>{label}</span>
      {area
        ? <textarea id={id} rows={3} value={value ?? ''} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
        : <input id={id} type={type} inputMode={type === 'number' ? 'numeric' : undefined} value={value ?? ''} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />}
      {help && <span className="help">{help}</span>}
    </label>
  )
}

// ---------------------------------------------------------------- form

function FieldRow({ field, index, count, onChange, onMove, onRemove }: {
  field: FieldDoc; index: number; count: number; onChange: (f: FieldDoc) => void; onMove: (to: number) => void; onRemove: () => void
}) {
  const hasOptions = field.type === 'select' || field.type === 'multiselect'
  // the box keeps exactly what was typed (blank lines too); the document gets the non-empty lines
  const [optText, setOptText] = useState((field.options ?? []).join('\n'))
  const setType = (type: FieldType) => {
    const next: FieldDoc = { ...field, type }
    if (type === 'select' || type === 'multiselect') {
      next.options = field.options?.length ? field.options : ['Option 1']
      setOptText(next.options.join('\n'))
    }
    else delete next.options
    onChange(next)
  }
  return (
    <li className="field-row">
      <div className="row between wrap">
        <strong>Question {index + 1}</strong>
        <div className="row">
          <button type="button" className="btn btn-small" disabled={index === 0} onClick={() => onMove(index - 1)} aria-label={`Move question ${index + 1} up`}>↑</button>
          <button type="button" className="btn btn-small" disabled={index === count - 1} onClick={() => onMove(index + 1)} aria-label={`Move question ${index + 1} down`}>↓</button>
          <button type="button" className="btn btn-small" disabled={count === 1} onClick={onRemove} aria-label={`Remove question ${index + 1}`}>Remove</button>
        </div>
      </div>
      <Text label="Question" value={field.label} onChange={(label) => onChange({ ...field, label })} />
      <div className="grid-2">
        <label className="field-group"><span>Answer type</span>
          <select value={field.type} onChange={(e) => setType(e.target.value as FieldType)}>
            {FIELD_TYPES.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
          </select>
        </label>
        <label className="check"><input type="checkbox" checked={!!field.required} onChange={(e) => onChange({ ...field, required: e.target.checked })} /> Required</label>
      </div>
      {hasOptions && (
        <Text label="Choices, one per line" area value={optText} onChange={(v) => { setOptText(v); onChange({ ...field, options: lines(v) }) }} />
      )}
      <Text label="Hint (optional)" value={field.help} onChange={(help) => onChange(help ? { ...field, help } : (({ help: _h, ...f }) => f)(field))} />
    </li>
  )
}

function FormConfig({ config, onChange }: Props) {
  const fields: FieldDoc[] = config.fields ?? []
  const set = (next: FieldDoc[]) => onChange({ ...config, fields: next })
  const update = (i: number, f: FieldDoc) => {
    // a question added here gets its key from its wording; one that already exists keeps its key, so saved answers still match
    const others = fields.filter((_, j) => j !== i).map((x) => x.key)
    const key = f._fresh ? uniqueKey(toKey(f.label, 'field'), others) : f.key
    set(fields.map((x, j) => (j === i ? { ...f, key } : x)))
  }
  return (
    <div className="stack">
      <Text label="Intro (optional)" area value={config.intro} onChange={(v) => onChange(put(config, 'intro', v))} />
      <ol className="field-list">
        {fields.map((f, i) => (
          <FieldRow key={f._uid ?? i} field={f} index={i} count={fields.length} onChange={(nf) => update(i, nf)} onMove={(to) => set(move(fields, i, to))} onRemove={() => set(fields.filter((_, j) => j !== i))} />
        ))}
      </ol>
      <button type="button" className="btn" disabled={fields.length >= 40} onClick={() => set([...fields, { _uid: uid(), _fresh: true, key: uniqueKey('new_question', fields.map((f) => f.key)), label: 'New question', type: 'text' }])}>
        + Add a question
      </button>
    </div>
  )
}

// ---------------------------------------------------------------- the others

function UploadConfig({ config, onChange }: Props) {
  const accept: string[] = config.accept ?? []
  const toggle = (ext: string, on: boolean) => onChange({ ...config, accept: on ? [...accept, ext].sort() : accept.filter((a) => a !== ext) })
  return (
    <div className="stack">
      <Text label="What to upload" area value={config.prompt} onChange={(v) => onChange(put(config, 'prompt', v))} placeholder="Your logo, in the highest quality you have" />
      <fieldset className="checks">
        <legend>File types allowed</legend>
        <div className="chips">
          {UPLOAD_EXTENSIONS.map((ext) => (
            <label key={ext} className="check check-chip"><input type="checkbox" checked={accept.includes(ext)} onChange={(e) => toggle(ext, e.target.checked)} /> {ext}</label>
          ))}
        </div>
      </fieldset>
      <div className="grid-3">
        <Text label="Largest file (MB)" type="number" value={config.max_mb?.toString()} onChange={(v) => onChange(put(config, 'max_mb', num(v)))} placeholder="10" />
        <Text label="At least" type="number" value={config.min_files?.toString()} onChange={(v) => onChange(put(config, 'min_files', num(v)))} placeholder="1" />
        <Text label="At most" type="number" value={config.max_files?.toString()} onChange={(v) => onChange(put(config, 'max_files', num(v)))} placeholder="5" />
      </div>
    </div>
  )
}

function ApprovalConfig({ config, onChange }: Props) {
  const d = config.deliverable ?? { kind: 'text' }
  const need = { text: 'text', link: 'url', file: 'file_name' } as const
  const setKind = (kind: keyof typeof need) => onChange({ ...config, deliverable: { kind, [need[kind]]: d[need[kind]] ?? '' } })
  const setValue = (v: string) => onChange({ ...config, deliverable: { kind: d.kind, [need[d.kind as keyof typeof need]]: v } })
  return (
    <div className="stack">
      <Text label="What you're asking" area value={config.prompt} onChange={(v) => onChange(put(config, 'prompt', v))} placeholder="Please check the scope and approve it" />
      <fieldset className="checks">
        <legend>What they approve</legend>
        <div className="chips">
          {(['text', 'link', 'file'] as const).map((k) => (
            <label key={k} className="check check-chip"><input type="radio" name={`kind-${d.kind}`} checked={d.kind === k} onChange={() => setKind(k)} /> {k === 'text' ? 'Some text' : k === 'link' ? 'A link' : 'A file'}</label>
          ))}
        </div>
      </fieldset>
      {d.kind === 'text' && <Text label="The text" area value={d.text} onChange={setValue} />}
      {d.kind === 'link' && <Text label="The link (https://)" type="url" value={d.url} onChange={setValue} />}
      {d.kind === 'file' && <Text label="The file's name" value={d.file_name} onChange={setValue} help="Attach the file itself on the onboarding page." />}
    </div>
  )
}

function BookCallConfig({ config, onChange }: Props) {
  return (
    <div className="stack">
      <Text label="Booking page (https://)" type="url" value={config.url} onChange={(v) => onChange({ ...config, url: v })} placeholder="https://cal.com/you/kickoff" />
      <Text label="Length in minutes" type="number" value={config.duration_minutes?.toString()} onChange={(v) => onChange(put(config, 'duration_minutes', num(v)))} />
      <Text label="Instructions (optional)" area value={config.instructions} onChange={(v) => onChange(put(config, 'instructions', v))} />
    </div>
  )
}

function ConnectConfig({ config, onChange }: Props) {
  return (
    <div className="stack">
      <Text label="What they connect" value={config.label} onChange={(v) => onChange({ ...config, label: v, provider: toKey(v, 'account') })} placeholder="Google Business Profile" />
      <label className="field-group"><span>How</span>
        <select value={config.access_mode ?? 'delegated'} onChange={(e) => onChange({ ...config, access_mode: e.target.value })}>
          <option value="delegated">They add you as a user</option>
          <option value="oauth">They sign in and allow access</option>
        </select>
      </label>
      <Text label="Where to start (https://, optional)" type="url" value={config.start_url} onChange={(v) => onChange(put(config, 'start_url', v))} />
      <Text label="Instructions (optional)" area value={config.instructions} onChange={(v) => onChange(put(config, 'instructions', v))} />
      <p className="help">No password or token is ever collected. The client only says it's done.</p>
    </div>
  )
}

function InternalTaskConfig({ config, onChange }: Props) {
  return (
    <div className="stack">
      <Text label="Notes" area value={config.notes} onChange={(v) => onChange(put(config, 'notes', v))} />
      <Text label="Checklist, one item per line" area value={(config.checklist ?? []).join('\n')} onChange={(v) => onChange(put(config, 'checklist', lines(v)))} />
    </div>
  )
}

const EDITORS: Record<string, (p: Props) => React.JSX.Element> = {
  form: FormConfig, upload: UploadConfig, approval: ApprovalConfig, book_call: BookCallConfig, connect: ConnectConfig, internal_task: InternalTaskConfig,
}

export function ConfigEditor({ type, ...p }: Props & { type: string }) {
  const Editor = EDITORS[type]
  if (!Editor) return <p className="help">This step type has no settings you can change here. Use YAML import to edit it.</p>
  return <Editor {...p} />
}
