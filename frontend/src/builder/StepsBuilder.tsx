import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, closestCenter, pointerWithin, useDraggable, useDroppable, useSensor, useSensors,
  type CollisionDetection, type DragEndEvent, type DragStartEvent,
} from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useId, useState } from 'react'
import { Icon } from '../components/Icon'
import { ConfigEditor } from './ConfigEditor'
import { FIELD_TYPES, STEP_KINDS, byStage, kindOf, move, needsSignoff, newStep, toKey, uid, uniqueKey, isInternal, withVisibility, type FieldDoc, type FieldType, type SectionDoc, type StepDoc, type StepKind } from './doc'

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
// Each stage (and the steps outside any stage) has its own drop zone at its end: `end:<stage key>`, `end:` for no stage.
const END = 'end:'

// ---------------------------------------------------------------- palette

function PaletteItem({ kind, where, onAdd }: { kind: StepKind; where: string; onAdd: () => void }) {
  const { setNodeRef, listeners, isDragging } = useDraggable({ id: `${NEW}${kind.type}` })
  return (
    <li>
      {/* Only the pointer starts a drag here. Enter and Space stay a plain click that adds to the end, so the keyboard works too. */}
      <button ref={setNodeRef} type="button" className={`palette-item${isDragging ? ' is-dragging' : ''}`} onPointerDown={listeners?.onPointerDown as React.PointerEventHandler<HTMLButtonElement> | undefined} onClick={onAdd}>
        <Icon name={kind.type} />
        <span><strong>{kind.label}</strong><span className="help">{kind.help}</span></span>
        <span className="sr-only">: add {where}</span>
      </button>
    </li>
  )
}

function EndZone({ stage, empty, title }: { stage: string; empty: boolean; title?: string }) {
  const { setNodeRef, isOver } = useDroppable({ id: `${END}${stage}` })
  return (
    <div ref={setNodeRef} className={`drop-end${isOver ? ' is-over' : ''}`}>
      {empty ? (title ? `Drag steps into “${title}” from the menu, or from another stage.` : 'Drag a step here from the menu, or tap one there to add it.') : 'Drop here to add at the end'}
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
        <label className="field-group" htmlFor={`${id}-s`}><span>Stage</span>
          <select id={`${id}-s`} value={step.section ?? ''} onChange={(e) => onChange({ ...step, section: e.target.value })}>
            <option value="">Not in a stage</option>
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

function StepItem({ step, first, last, open, locked, sections, dropping, onToggle, onChange, onMove, onRemove }: {
  step: StepDoc; first: boolean; last: boolean; open: boolean; locked: boolean; sections: SectionDoc[]; dropping: boolean
  onToggle: () => void; onChange: (s: StepDoc) => void; onMove: (by: -1 | 1) => void; onRemove: () => void
}) {
  const { setNodeRef, attributes, listeners, transform, transition, isDragging, isOver } = useSortable({ id: step._uid! })
  const kind = kindOf(step.type)
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
            {kind?.label ?? step.type}{step.due_offset_days != null ? ` · due day ${step.due_offset_days}` : ''}{isInternal(step) ? ' · only you see it' : ''}{locked ? ' · has answers' : ''}
          </span>
        </button>
        <div className="step-item-actions">
          <button type="button" className="btn btn-small" disabled={first} onClick={() => onMove(-1)} aria-label={`Move “${step.title}” up`}>↑</button>
          <button type="button" className="btn btn-small" disabled={last} onClick={() => onMove(1)} aria-label={`Move “${step.title}” down`}>↓</button>
          <button type="button" className="btn btn-small" disabled={locked} onClick={onRemove} aria-label={`Remove “${step.title}”`}
            title={locked ? 'This step already has answers, files or comments.' : undefined}>Remove</button>
        </div>
      </div>
      {open && <div id={panel}><StepEditor step={step} sections={sections} locked={locked} onChange={onChange} /></div>}
    </li>
  )
}

// ---------------------------------------------------------------- stages

function StageHead({ stage, index, count, steps, onChange, onMove, onRemove }: {
  stage: SectionDoc; index: number; count: number; steps: number
  onChange: (s: SectionDoc) => void; onMove: (by: -1 | 1) => void; onRemove: () => void
}) {
  const id = useId()
  return (
    <div className="stage-head">
      <span className="stage-number" aria-hidden="true">{index + 1}</span>
      <label className="field-group grow" htmlFor={`${id}-t`}><span className="sr-only">Stage {index + 1} title</span>
        <input id={`${id}-t`} className="stage-title" value={stage.title} maxLength={200} onChange={(e) => onChange({ ...stage, title: e.target.value })} />
      </label>
      <div className="step-item-actions">
        <button type="button" className="btn btn-small" disabled={index === 0} onClick={() => onMove(-1)} aria-label={`Move stage “${stage.title}” up`}>↑</button>
        <button type="button" className="btn btn-small" disabled={index === count - 1} onClick={() => onMove(1)} aria-label={`Move stage “${stage.title}” down`}>↓</button>
        <button type="button" className="btn btn-small" onClick={onRemove} aria-label={`Remove stage “${stage.title}”`}
          title={steps ? 'Its steps stay, outside any stage.' : undefined}>Remove</button>
      </div>
      <label className="check stage-signoff">
        <input type="checkbox" checked={needsSignoff(stage)} onChange={(e) => onChange({ ...stage, signoff: e.target.checked })} />
        <span>Your team signs this stage off before {index === count - 1 ? 'the onboarding finishes' : 'the next one opens to the client'}</span>
      </label>
    </div>
  )
}

function AddStage({ sections, onAdd }: { sections: SectionDoc[]; onAdd: (s: SectionDoc) => void }) {
  const [title, setTitle] = useState('')
  const id = useId()
  function add() {
    const t = title.trim()
    if (!t) return
    onAdd({ key: uniqueKey(toKey(t, 'stage'), sections.map((s) => s.key)), title: t, signoff: true })
    setTitle('')
  }
  // not a <form>: the builder sits inside other forms, and forms can't nest
  return (
    <div className="row wrap add-stage">
      <label className="field-group grow" htmlFor={id}><span>{sections.length ? 'New stage' : 'Group the steps into stages'}</span>
        <input id={id} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder={sections.length ? 'Launch' : 'Discovery'}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
      </label>
      <button type="button" className="btn" disabled={!title.trim() || sections.length >= 20} onClick={add}>Add stage</button>
    </div>
  )
}

// ---------------------------------------------------------------- the builder

export default function StepsBuilder({ value, onChange, locked = [] }: Props) {
  const { sections } = value
  // Steps always sit with their stage, in stage order, so the list reads (and the client works through it) one stage at a time.
  const steps = byStage(sections, value.steps)
  const [open, setOpen] = useState<string | null>(null)
  const [active, setActive] = useState<string | null>(null)
  const [said, setSaid] = useState('')
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const isLocked = (s: StepDoc) => !s._fresh && locked.includes(s.key)
  const setSteps = (next: StepDoc[]) => onChange({ ...value, steps: byStage(sections, next) })
  const setSections = (next: SectionDoc[], nextSteps = steps) => onChange({ sections: next, steps: byStage(next, nextSteps) })
  const known = new Set(sections.map((s) => s.key))
  const stageOf = (s: StepDoc) => (s.section && known.has(s.section) ? s.section : '')
  const titleOf = (key: string) => sections.find((s) => s.key === key)?.title ?? 'no stage'

  /** Where a tap in the menu adds a step: the stage of the step being edited, else the last stage. */
  const openStep = steps.find((s) => s._uid === open)
  const tapStage = openStep ? stageOf(openStep) : sections.length ? sections[sections.length - 1].key : ''

  function insert(type: string, stage: string, before?: number) {
    const s = { ...newStep(type, steps.map((x) => x.key)), section: stage }
    const at = before ?? steps.length
    setSteps([...steps.slice(0, at), s, ...steps.slice(at)])
    setOpen(s._uid!)
    setSaid(`Added “${s.title}”${stage ? ` to ${titleOf(stage)}` : ''} as step ${byStage(sections, [...steps.slice(0, at), s, ...steps.slice(at)]).indexOf(s) + 1} of ${steps.length + 1}.`)
  }

  function update(uidOf: string, s: StepDoc) {
    const others = steps.filter((x) => x._uid !== uidOf).map((x) => x.key)
    const key = s._fresh ? uniqueKey(toKey(s.title || kindOf(s.type)?.label || 'step'), others) : s.key
    setSteps(steps.map((x) => (x._uid === uidOf ? withVisibility({ ...s, key }) : x)))
  }

  function addField(uidOf: string, type: FieldType) {
    const step = steps.find((x) => x._uid === uidOf)!
    const fields: FieldDoc[] = step.config.fields ?? []
    const label = 'New question'
    const field: FieldDoc = { _uid: uid(), _fresh: true, key: uniqueKey(toKey(label, 'field'), fields.map((f) => f.key)), label, type }
    if (type === 'select' || type === 'multiselect') field.options = ['Option 1', 'Option 2']
    setSteps(steps.map((x) => (x._uid === uidOf ? { ...x, config: { ...x.config, fields: [...fields, field] } } : x)))
    setSaid(`Added a ${FIELD_TYPES.find((f) => f.type === type)?.label.toLowerCase()} question to “${step.title}”.`)
  }

  function remove(uidOf: string) {
    setSaid(`Removed “${steps.find((x) => x._uid === uidOf)?.title}”.`)
    setSteps(steps.filter((x) => x._uid !== uidOf))
  }

  /** ↑/↓ moves a step within its stage; the Stage list in its settings moves it to another. */
  function nudge(uidOf: string, by: -1 | 1) {
    const i = steps.findIndex((x) => x._uid === uidOf)
    const s = steps[i]
    setSteps(move(steps, i, i + by))
    const group = steps.filter((x) => stageOf(x) === stageOf(s))
    setSaid(`Moved “${s.title}” to position ${group.indexOf(s) + by + 1}${sections.length ? ` in ${stageOf(s) ? titleOf(stageOf(s)) : 'the steps outside a stage'}` : ''}.`)
  }

  function onDragStart(e: DragStartEvent) {
    setActive(String(e.active.id))
  }

  function onDragEnd({ active: a, over }: DragEndEvent) {
    setActive(null)
    if (!over) return
    const id = String(a.id)
    const overId = String(over.id)
    const target = overId.startsWith(END) ? null : steps.find((s) => s._uid === overId)
    if (!overId.startsWith(END) && !target) return
    const stage = target ? stageOf(target) : overId.slice(END.length)
    if (id.startsWith(NEW)) return insert(id.slice(NEW.length), stage, target ? steps.indexOf(target) : undefined)
    const moving = steps.find((s) => s._uid === id)
    if (!moving || moving === target) return
    const rest = steps.filter((s) => s !== moving)
    const at = target ? rest.indexOf(target) : rest.length
    const moved = { ...moving, section: stage }
    if (target && stageOf(moving) === stage && steps.indexOf(moving) < steps.indexOf(target)) {
      setSteps([...rest.slice(0, at + 1), moved, ...rest.slice(at + 1)])  // dragged down onto a step: it goes after it, as the list showed
    } else setSteps([...rest.slice(0, at), moved, ...rest.slice(at)])
    if (stageOf(moving) !== stage) setSaid(`Moved “${moving.title}” to ${titleOf(stage)}.`)
  }

  function removeStage(key: string) {
    setSaid(`Removed the stage “${titleOf(key)}”. Its steps are kept, outside any stage.`)
    setSections(sections.filter((x) => x.key !== key), steps.map((st) => (st.section === key ? { ...st, section: '' } : st)))
  }

  const groups: { stage: SectionDoc | null; steps: StepDoc[] }[] = [
    ...sections.map((st) => ({ stage: st, steps: steps.filter((s) => stageOf(s) === st.key) })),
    { stage: null, steps: steps.filter((s) => stageOf(s) === '') },
  ].filter((g) => g.stage || g.steps.length || !sections.length)

  const dragging = active?.startsWith(NEW) ? kindOf(active.slice(NEW.length)) : undefined
  const list = (g: { stage: SectionDoc | null; steps: StepDoc[] }) => (
    <>
      <SortableContext items={g.steps.map((s) => s._uid!)} strategy={verticalListSortingStrategy}>
        <ol className="step-list" aria-label={g.stage ? `Steps in ${g.stage.title}, in order` : sections.length ? 'Steps outside any stage' : 'Steps, in order'}>
          {g.steps.map((s, i) => (
            <StepItem key={s._uid} step={s} first={i === 0} last={i === g.steps.length - 1} open={open === s._uid} locked={isLocked(s)} sections={sections} dropping={!!dragging}
              onToggle={() => setOpen(open === s._uid ? null : s._uid!)} onChange={(ns) => update(s._uid!, ns)}
              onMove={(by) => nudge(s._uid!, by)} onRemove={() => remove(s._uid!)} />
          ))}
        </ol>
      </SortableContext>
      <EndZone stage={g.stage?.key ?? ''} empty={g.steps.length === 0} title={g.stage?.title} />
    </>
  )
  return (
    <DndContext sensors={sensors} collisionDetection={collide} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setActive(null)}>
      {/* Enter in a builder field must not submit a form the builder sits in (that would create the onboarding early) */}
      <div className="builder" onKeyDown={(e) => { if (e.key === 'Enter' && e.target instanceof HTMLInputElement) e.preventDefault() }}>
        <div className="builder-main stack">
          <h3>{sections.length ? 'Stages and steps' : 'Steps'} <span className="help">({steps.length} step{steps.length === 1 ? '' : 's'}{sections.length ? `, ${sections.length} stage${sections.length === 1 ? '' : 's'}` : ''})</span></h3>
          {groups.map((g) => g.stage ? (
            <section key={g.stage.key} className="stage-block" aria-label={`Stage ${sections.indexOf(g.stage) + 1}: ${g.stage.title}`}>
              <StageHead stage={g.stage} index={sections.indexOf(g.stage)} count={sections.length} steps={g.steps.length}
                onChange={(ns) => setSections(sections.map((x) => (x.key === ns.key ? ns : x)))}
                onMove={(by) => { const i = sections.indexOf(g.stage!); setSections(move(sections, i, i + by)); setSaid(`Moved the stage “${g.stage!.title}” to position ${i + by + 1}.`) }}
                onRemove={() => removeStage(g.stage!.key)} />
              {list(g)}
            </section>
          ) : (
            <section key="_none" className={sections.length ? 'stage-block stage-none' : 'stack'} aria-label={sections.length ? 'Not in a stage' : undefined}>
              {sections.length > 0 && <div className="stage-head"><strong>Not in a stage</strong><span className="help">Always open to the client</span></div>}
              {list(g)}
            </section>
          ))}
          <AddStage sections={sections} onAdd={(st) => { setSections([...sections, st]); setSaid(`Added the stage “${st.title}”.`) }} />
          <p className="sr-only" role="status" aria-live="polite">{said}</p>
        </div>
        <aside className="palette" aria-labelledby="palette-h">
          <h3 id="palette-h">Add a step</h3>
          <p className="help">Drag one into a stage, or tap it to add it{tapStage ? ` to “${titleOf(tapStage)}”` : ' at the end'}.</p>
          <ul>{STEP_KINDS.map((k) => <PaletteItem key={k.type} kind={k} where={tapStage ? `to “${titleOf(tapStage)}”` : 'to the end'} onAdd={() => insert(k.type, tapStage)} />)}</ul>
          {openStep && openStep.type === 'form' && (
            <div className="palette-group">
              <h3 id="fields-h">Add a question to “{openStep.title}”</h3>
              <ul className="palette-fields" aria-labelledby="fields-h">
                {FIELD_TYPES.map((f) => (
                  <li key={f.type}><button type="button" className="palette-item palette-field" onClick={() => addField(openStep._uid!, f.type)}><Icon name="plus" size={16} /> {f.label}</button></li>
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
