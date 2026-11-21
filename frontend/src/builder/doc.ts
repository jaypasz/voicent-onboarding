// The template document the builder edits. Same shape as backend/app/templates/schema.json; the server validates it again.
import { UPLOAD_TYPES } from '../lib/uploads'

export type Layout = 'focus' | 'checklist'
export type FieldType = 'text' | 'textarea' | 'select' | 'multiselect' | 'phone' | 'email' | 'url' | 'date' | 'checkbox'

/** Builder-only bookkeeping, stripped before anything is sent: a stable id for React, and whether the key may still follow the wording. */
export interface Meta {
  _uid?: string
  _fresh?: boolean
}

export interface FieldDoc extends Meta {
  key: string
  label: string
  type: FieldType
  required?: boolean
  help?: string
  options?: string[]
}

export interface SectionDoc {
  key: string
  title: string
}

export interface StepDoc extends Meta {
  key: string
  type: string
  title: string
  description?: string
  section?: string
  visibility?: 'client' | 'internal'
  assignee_role?: string
  due_offset_days?: number | null
  config: Record<string, any>
  show_if?: unknown
}

export interface TemplateDoc {
  name: string
  slug: string
  version?: number
  description?: string
  layout: Layout
  nudge_after_days?: number
  on_complete?: 'none' | 'provision_voicent_workspace'
  sections: SectionDoc[]
  steps: StepDoc[]
}

export interface StepKind {
  type: string
  label: string
  help: string
  make: () => Record<string, any>
}

/** What can be dragged in. Declared-but-unbuilt types (credential_share, info_video, payment_link) are left out, as the server refuses them. */
export const STEP_KINDS: StepKind[] = [
  { type: 'form', label: 'Form', help: 'Questions the client answers', make: () => ({ fields: [{ _fresh: true, key: 'your_answer', label: 'Your answer', type: 'text', required: true }] }) },
  { type: 'upload', label: 'File upload', help: 'Documents, logos, photos', make: () => ({ accept: ['pdf', 'png', 'jpg'], max_files: 5 }) },
  { type: 'approval', label: 'Approval', help: 'The client signs off on something', make: () => ({ deliverable: { kind: 'text', text: '' } }) },
  { type: 'book_call', label: 'Book a call', help: 'A link to your booking page', make: () => ({ url: '', duration_minutes: 30 }) },
  { type: 'connect', label: 'Connect an account', help: 'Record that access was given', make: () => ({ provider: 'account', label: 'Your account', access_mode: 'delegated' }) },
  { type: 'task', label: 'Task', help: 'Something to do, for the client or for you', make: () => ({ audience: 'client', checklist: [] }) },
]

export const kindOf = (type: string): StepKind | undefined => STEP_KINDS.find((k) => k.type === type)

export const FIELD_TYPES: { type: FieldType; label: string }[] = [
  { type: 'text', label: 'Short text' }, { type: 'textarea', label: 'Long text' }, { type: 'email', label: 'Email' }, { type: 'phone', label: 'Phone' },
  { type: 'url', label: 'Web address' }, { type: 'date', label: 'Date' }, { type: 'select', label: 'Pick one' }, { type: 'multiselect', label: 'Pick several' },
  { type: 'checkbox', label: 'Tick box' },
]

export const UPLOAD_EXTENSIONS = Object.keys(UPLOAD_TYPES).sort()

/** A key the server accepts (^[a-z][a-z0-9_]{0,63}$), made from a title. */
export function toKey(text: string, fallback = 'step'): string {
  let k = text.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  if (!/^[a-z]/.test(k)) k = `${fallback}_${k}`.replace(/_+$/, '')
  return k.slice(0, 64).replace(/_+$/, '') || fallback
}

/** A slug the server accepts (^[a-z0-9][a-z0-9-]{0,79}$). */
export function toSlug(text: string): string {
  return text.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80).replace(/-+$/, '')
}

export function uniqueKey(base: string, taken: Iterable<string>): string {
  const used = new Set(taken)
  if (!used.has(base)) return base
  for (let n = 2; ; n++) {
    const k = `${base.slice(0, 60)}_${n}`
    if (!used.has(k)) return k
  }
}

let counter = 0
export const uid = (): string => `u${++counter}`

const withFieldUids = (s: StepDoc): StepDoc =>
  s.type === 'form' && Array.isArray(s.config?.fields) ? { ...s, config: { ...s.config, fields: s.config.fields.map((f: FieldDoc) => ({ ...f, _uid: f._uid ?? uid() })) } } : s

/** Ready for the builder: every step and question gets an id. Nothing loaded from the server is fresh. */
export const prepare = (steps: StepDoc[]): StepDoc[] => steps.map((s) => withFieldUids({ ...s, _uid: s._uid ?? uid() }))

function strip<T extends Meta>(x: T): Omit<T, keyof Meta> {
  const { _uid: _a, _fresh: _b, ...rest } = x
  return rest
}

/** Exactly what the server expects: no builder bookkeeping. */
export function clean(steps: StepDoc[]): StepDoc[] {
  return steps.map((s) => {
    const out = strip(s) as StepDoc
    if (s.type === 'form' && Array.isArray(s.config?.fields)) out.config = { ...s.config, fields: s.config.fields.map((f: FieldDoc) => strip(f)) }
    return out
  })
}

export function newStep(type: string, taken: Iterable<string>): StepDoc {
  const kind = kindOf(type)
  const title = kind ? kind.label : 'New step'
  return withFieldUids({
    _uid: uid(), _fresh: true,
    key: uniqueKey(toKey(title), taken), type, title, description: '', section: '', visibility: isInternal({ type, config: kind ? kind.make() : {} }) ? 'internal' : 'client',
    assignee_role: '', due_offset_days: null, config: kind ? kind.make() : {},
  })
}

/** Only a task for the team is hidden from the client; every other step is theirs. */
export const isInternal = (s: { type: string; config?: Record<string, any> }): boolean => s.type === 'task' && s.config?.audience === 'team'

/** A step's visibility follows its type and, for a task, who it is for, as the server enforces. */
export function withVisibility(s: StepDoc): StepDoc {
  return { ...s, visibility: isInternal(s) ? 'internal' : 'client' }
}

export function move<T>(list: T[], from: number, to: number): T[] {
  const out = list.slice()
  const [item] = out.splice(from, 1)
  out.splice(to, 0, item)
  return out
}
