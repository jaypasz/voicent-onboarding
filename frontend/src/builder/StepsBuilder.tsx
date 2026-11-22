import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, closestCenter, pointerWithin, useDraggable, useDroppable, useSensor, useSensors,
  type CollisionDetection, type DragEndEvent, type DragStartEvent,
} from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useId, useState } from 'react'
import { Icon } from '../components/Icon'
import { ConfigEditor } from './ConfigEditor'
import { FIELD_TYPES, STEP_KINDS, kindOf, move, newStep, toKey, uid, uniqueKey, isInternal, withVisibility, type FieldDoc, type FieldType, type SectionDoc, type StepDoc, type StepKind } from './doc'

export interface BuilderValue {
  sections: SectionDoc[]
  steps: StepDoc[]
}

interface Props {
  value: BuilderValue
  onChange: (v: BuilderValue) => void
  /** Keys of steps that already hold answers, files or comments: they stay, and keep their type and key. */
  locked?: string[]
}

const NEW = 'new:'
// What's under the pointer wins: an open card is tall, so its centre can be far from where you point.
// Keyboard moves have no pointer, so they fall back to the closest centre.
const collide: CollisionDetection = (args) => { const hits = pointerWithin(args); return hits.length ? hits : closestCenter(args) }
const END = 'list-end'

// ---------------------------------------------------------------- palette

function PaletteItem({ kind, onAdd }: { kind: StepKind; onAdd: () => void }) {
  const { setNodeRef, listeners, isDragging } = useDraggable({ id: `${NEW}${kind.type}` })
  return (
    <li>
      {/* Only the pointer starts a drag here. Enter and Space stay a plain click that adds to the end, so the keyboard works too. */}
      <button ref={setNodeRef} type="button" className={`palette-item${isDragging ? ' is-dragging' : ''}`} onPointerDown={listeners?.onPointerDown as React.PointerEventHandler<HTMLButtonElement> | undefined} onClick={onAdd}>
        <Icon name={kind.type} />
        <span><strong>{kind.label}</strong><span className="help">{kind.help}</span></span>
        <span className="sr-only">: add to the end</span>
      </button>
    </li>
  )
}

function EndZone({ empty }: { empty: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: END })
  return (
    <div ref={setNodeRef} className={`drop-end${isOver ? ' is-over' : ''}`}>
      {empty ? 'Drag a step here from the menu, or tap one there to add it.' : 'Drop here to add at the end'}
    </div>
  )
}

// ---------------------------------------------------------------- one step

function StepEditor({ step, sections, locked, onChange }: { step: StepDoc; sections: SectionDoc[]; locked: boolean; onChange: (s: StepDoc) => void }) {
  const id = useId()
  const internal = isInternal(step)
  return (
    <div className="step-editor stack">
      <label className="field-group" htmlFor={`${id}-t`}><span>Title</span>
        <input id={`${id}-t`} value={step.title} maxLength={200} onChange={(e) => onChange({ ...step, title: e.target.value })} />
      </label>
      <label className="field-group" htmlFor={`${id}-d`}><span>Description (optional)</span>
        <textarea id={`${id}-d`} rows={2} maxLength={2000} value={step.description ?? ''} onChange={(e) => onChange({ ...step, description: e.target.value })} />
      </label>
      <div className="grid-3">
        <label className="field-group" htmlFor={`${id}-s`}><span>Section</span>
          <select id={`${id}-s`} value={step.section ?? ''} onChange={(e) => onChange({ ...step, section: e.target.value })}>
            <option value="">No section</option>
            {sections.map((s) => <option key={s.key} value={s.key}>{s.title}</option>)}
          </select>
        </label>
        <label className="field-group" htmlFor={`${id}-due`}><span>Due, days after sending</span>
          <input id={`${id}-due`} type="number" inputMode="numeric" min={0} max={365} value={step.due_offset_days ?? ''} placeholder="No due date"
            onChange={(e) => onChange({ ...step, due_offset_days: e.target.value === '' ? null : Math.trunc(Number(e.target.value)) })} />
        </label>
        {!internal && (
          <label className="field-group" htmlFor={`${id}-r`}><span>Who answers (role)</span>
            <input id={`${id}-r`} value={step.assignee_role ?? ''} maxLength={40} placeholder="Anyone" onChange={(e) => onChange({ ...step, assignee_role: e.target.value.trim().toLowerCase() })} />
          </label>
        )}
      </div>
      {!internal && <p className="help">A role picks the contact with that role, for example “owner”. Leave it blank and anyone with a link can answer.</p>}
      <h4>{kindOf(step.type)?.label ?? step.type} settings</h4>
      <ConfigEditor type={step.type} locked={locked} config={step.config} onChange={(config) => onChange({ ...step, config })} />
      <p className="help">Key: <code>{step.key}</code>{locked ? ' · has answers, files or comments, so it stays and keeps its type' : ''}</p>
    </div>
  )
}

function StepItem({ step, index, count, open, locked, sections, dropping, onToggle, onChange, onMove, onRemove }: {
  step: StepDoc; index: number; count: number; open: boolean; locked: boolean; sections: SectionDoc[]; dropping: boolean
  onToggle: () => void; onChange: (s: StepDoc) => void; onMove: (to: number) => void; onRemove: () => void
}) {
  const { setNodeRef, attributes, listeners, transform, transition, isDragging, isOver } = useSortable({ id: step._uid! })
  const kind = kindOf(step.type)
  const section = sections.find((s) => s.key === step.section)
  const panel = `${step._uid}-panel`
  return (
    <li ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`step-item${open ? ' is-open' : ''}${isDragging ? ' is-dragging' : ''}${dropping && isOver ? ' drop-before' : ''}`}>
      <div className="step-item-head">
        <button type="button" className="drag-handle" {...attributes} {...listeners} aria-label={`Drag “${step.title}” to move it. Space to pick up, arrows to move, Space to drop.`}>
          <Icon name="grip" />
        </button>
        <span className="step-item-icon"><Icon name={step.type} /></span>
        <button type="button" className="step-item-title" aria-expanded={open} aria-controls={panel} onClick={onToggle}>
          <strong>{step.title || 'Untitled step'}</strong>
          <span className="help">
            {kind?.label ?? step.type}{section ? ` · ${section.title}` : ''}{isInternal(step) ? ' · only you see it' : ''}{locked ? ' · has answers' : ''}
          </span>
        </button>
        <div className="step-item-actions">
          <button type="button" className="btn btn-small" disabled={index === 0} onClick={() => onMove(index - 1)} aria-label={`Move “${step.title}” up`}>↑</button>
          <button type="button" className="btn btn-small" disabled={index === count - 1} onClick={() => onMove(index + 1)} aria-label={`Move “${step.title}” down`}>↓</button>
          <button type="button" className="btn btn-small" disabled={locked} onClick={onRemove} aria-label={`Remove “${step.title}”`}
            title={locked ? 'This step already has answers, files or comments.' : undefined}>Remove</button>
        </div>
      </div>
      {open && <div id={panel}><StepEditor step={step} sections={sections} locked={locked} onChange={onChange} /></div>}
    </li>
  )
}

// ---------------------------------------------------------------- sections

function SectionsPanel({ value, onChange }: Props) {
  const [title, setTitle] = useState('')
  const used = (key: string) => value.steps.filter((s) => s.section === key).length
  function add() {
    const t = title.trim()
    if (!t) return
    onChange({ ...value, sections: [...value.sections, { key: uniqueKey(toKey(t, 'section'), value.sections.map((s) => s.key)), title: t }] })
    setTitle('')
  }
  return (
    <details className="card sections-panel">
      <summary><strong>Sections</strong> <span className="help">({value.sections.length}) group steps under a heading</span></summary>
      <ul className="cards">
        {value.sections.map((s, i) => (
          <li key={s.key} className="row wrap">
            <label className="field-group grow"><span className="sr-only">Section title</span>
              <input value={s.title} maxLength={200} onChange={(e) => onChange({ ...value, sections: value.sections.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)) })} />
            </label>
            <span className="help">{used(s.key)} step{used(s.key) === 1 ? '' : 's'}</span>
            <button type="button" className="btn btn-small" aria-label={`Remove section ${s.title}`}
              onClick={() => onChange({ sections: value.sections.filter((x) => x.key !== s.key), steps: value.steps.map((st) => (st.section === s.key ? { ...st, section: '' } : st)) })}>Remove</button>
          </li>
        ))}
      </ul>
      {/* not a <form>: the builder sits inside other forms, and forms can't nest */}
      <div className="row wrap">
        <label className="field-group grow"><span>New section</span>
          <input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="Your company"
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
        </label>
        <button type="button" className="btn" disabled={!title.trim() || value.sections.length >= 20} onClick={add}>Add section</button>
      </div>
    </details>
  )
}

// ---------------------------------------------------------------- the builder

export default function StepsBuilder({ value, onChange, locked = [] }: Props) {
  const { steps, sections } = value
  const [open, setOpen] = useState<string | null>(null)
  const [active, setActive] = useState<string | null>(null)
  const [said, setSaid] = useState('')
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const isLocked = (s: StepDoc) => !s._fresh && locked.includes(s.key)
  const setSteps = (next: StepDoc[]) => onChange({ ...value, steps: next })

  function insert(type: string, at: number) {
    const s = newStep(type, steps.map((x) => x.key))
    setSteps([...steps.slice(0, at), s, ...steps.slice(at)])
    setOpen(s._uid!)
    setSaid(`Added “${s.title}” as step ${at + 1} of ${steps.length + 1}.`)
  }

  function update(i: number, s: StepDoc) {
    const others = steps.filter((_, j) => j !== i).map((x) => x.key)
    const key = s._fresh ? uniqueKey(toKey(s.title || kindOf(s.type)?.label || 'step'), others) : s.key
    setSteps(steps.map((x, j) => (j === i ? withVisibility({ ...s, key }) : x)))
  }

  const openIndex = steps.findIndex((s) => s._uid === open)

  function addField(i: number, type: FieldType) {
    const step = steps[i]
    const fields: FieldDoc[] = step.config.fields ?? []
    const label = 'New question'
    const field: FieldDoc = { _uid: uid(), _fresh: true, key: uniqueKey(toKey(label, 'field'), fields.map((f) => f.key)), label, type }
    if (type === 'select' || type === 'multiselect') field.options = ['Option 1', 'Option 2']
    setSteps(steps.map((x, j) => (j === i ? { ...x, config: { ...x.config, fields: [...fields, field] } } : x)))
    setSaid(`Added a ${FIELD_TYPES.find((f) => f.type === type)?.label.toLowerCase()} question to “${step.title}”.`)
  }

  function remove(i: number) {
    setSaid(`Removed “${steps[i].title}”.`)
    setSteps(steps.filter((_, j) => j !== i))
  }

  function onDragStart(e: DragStartEvent) {
    setActive(String(e.active.id))
  }

  function onDragEnd({ active: a, over }: DragEndEvent) {
    setActive(null)
    if (!over) return
    const id = String(a.id)
    const overIndex = over.id === END ? steps.length : steps.findIndex((s) => s._uid === over.id)
    if (overIndex < 0) return
    if (id.startsWith(NEW)) return insert(id.slice(NEW.length), overIndex)
    const from = steps.findIndex((s) => s._uid === id)
    const to = Math.min(overIndex, steps.length - 1)
    if (from >= 0 && from !== to) setSteps(move(steps, from, to))
  }

  const dragging = active?.startsWith(NEW) ? kindOf(active.slice(NEW.length)) : undefined
  return (
    <DndContext sensors={sensors} collisionDetection={collide} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setActive(null)}>
      {/* Enter in a builder field must not submit a form the builder sits in (that would create the onboarding early) */}
      <div className="builder" onKeyDown={(e) => { if (e.key === 'Enter' && e.target instanceof HTMLInputElement) e.preventDefault() }}>
        <div className="builder-main stack">
          <SectionsPanel value={value} onChange={onChange} />
          <h3>Steps <span className="help">({steps.length})</span></h3>
          <SortableContext items={steps.map((s) => s._uid!)} strategy={verticalListSortingStrategy}>
            <ol className="step-list" aria-label="Steps, in order">
              {steps.map((s, i) => (
                <StepItem key={s._uid} step={s} index={i} count={steps.length} open={open === s._uid} locked={isLocked(s)} sections={sections} dropping={!!dragging}
                  onToggle={() => setOpen(open === s._uid ? null : s._uid!)} onChange={(ns) => update(i, ns)}
                  onMove={(to) => { setSteps(move(steps, i, to)); setSaid(`Moved “${s.title}” to position ${to + 1}.`) }} onRemove={() => remove(i)} />
              ))}
            </ol>
          </SortableContext>
          <EndZone empty={steps.length === 0} />
          <p className="sr-only" role="status" aria-live="polite">{said}</p>
        </div>
        <aside className="palette" aria-labelledby="palette-h">
          <h3 id="palette-h">Add a step</h3>
          <p className="help">Drag one onto the list, or tap it to add it at the end.</p>
          <ul>{STEP_KINDS.map((k) => <PaletteItem key={k.type} kind={k} onAdd={() => insert(k.type, steps.length)} />)}</ul>
          {openIndex >= 0 && steps[openIndex].type === 'form' && (
            <div className="palette-group">
              <h3 id="fields-h">Add a question to “{steps[openIndex].title}”</h3>
              <ul className="palette-fields" aria-labelledby="fields-h">
                {FIELD_TYPES.map((f) => (
                  <li key={f.type}><button type="button" className="palette-item palette-field" onClick={() => addField(openIndex, f.type)}><Icon name="plus" size={16} /> {f.label}</button></li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
      <DragOverlay>{dragging ? <div className="palette-item is-overlay"><Icon name={dragging.type} /><strong>{dragging.label}</strong></div> : null}</DragOverlay>
    </DndContext>
  )
}
