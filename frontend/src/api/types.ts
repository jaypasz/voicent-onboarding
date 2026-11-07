export type StepStatus = 'pending' | 'in_progress' | 'done' | 'skipped'
export type OnboardingStatus = 'draft' | 'active' | 'paused' | 'completed' | 'archived'
export type Layout = 'focus' | 'checklist'
export type StepType = 'form' | 'upload' | 'connect' | 'book_call' | 'approval' | 'internal_task' | string

export interface Progress {
  done: number
  total: number
}

export interface Comment {
  id: string
  author_kind: 'client' | 'admin'
  author_label: string
  body: string
  client_visible?: boolean
  created_at: string
}

export interface FileRef {
  id: string
  name: string
  size: number
  content_type?: string
}

export interface FormField {
  key: string
  label: string
  type: 'text' | 'textarea' | 'select' | 'multiselect' | 'phone' | 'email' | 'url' | 'date' | 'checkbox'
  required?: boolean
  help?: string
  options?: string[]
}

// ------------------------------------------------------------------ client portal

export interface PortalStep {
  key: string
  type: StepType
  title: string
  description: string
  section: string
  position: number
  status: StepStatus
  due_at: string | null
  config: Record<string, any>
  assignee: { id: string; name: string; is_you: boolean } | null
  can_write: boolean
  response: Record<string, any> | null
  files: FileRef[]
  comments: Comment[]
}

export interface PortalView {
  title: string
  layout: Layout
  status: OnboardingStatus
  client_name: string
  contact: { id: string; name: string }
  sections: { key: string; title: string }[]
  progress: Progress
  steps: PortalStep[]
}

// ------------------------------------------------------------------ admin

export interface Contact {
  id: string
  client_id: string
  name: string
  email: string
  phone: string
  role: string
  sms_consent: boolean
  sms_consent_source: string
}

export interface Client {
  id: string
  name: string
  kind: 'trades' | 'agency' | 'msp' | 'other'
  status: 'active' | 'archived'
  notes: string
  timezone: string
  created_at: string
  contacts: Contact[]
}

export interface TemplateSummary {
  id: string
  name: string
  slug: string
  current_version: number
  archived: boolean
}

export interface TemplateDetail extends TemplateSummary {
  document: {
    name: string
    slug: string
    layout: Layout
    description: string
    sections: { key: string; title: string }[]
    steps: { key: string; type: string; title: string; section: string; visibility: string }[]
  }
  versions: number[]
  new_version?: boolean
}

export type Attention = 'nudges_exhausted' | 'unreachable' | null

export interface OnboardingSummary {
  id: string
  client_id: string
  title: string
  layout: Layout
  status: OnboardingStatus
  started_at: string | null
  completed_at: string | null
  last_activity_at: string
  nudges_paused: boolean
  attention: Attention
  progress: Progress
}

export interface AdminStep {
  id: string
  key: string
  type: StepType
  title: string
  section: string
  position: number
  visibility: 'client' | 'internal'
  status: StepStatus
  assignee_contact_id: string | null
  due_at: string | null
  completed_at: string | null
  config: Record<string, any>
  response: { revision: number; data: Record<string, any>; submitted_by: string; submitted_at: string } | null
  revisions: number
  files: FileRef[]
  comments: Comment[]
}

export interface OnboardingDetail extends OnboardingSummary {
  steps: AdminStep[]
}

export interface LinkInfo {
  id: string
  contact_id: string
  contact_name: string
  expires_at: string
  revoked_at: string | null
  last_used_at: string | null
  usable: boolean
  url?: string
}

export interface SentOnboarding extends OnboardingDetail {
  links: LinkInfo[]
}

export interface YamlImportResult {
  ok: boolean
  problems: string[]
  id?: string
  new_version?: boolean
  document?: unknown
}

export interface Features {
  sms: boolean
  email: boolean
  reminders: boolean
  aios_sync: boolean
  uploads: boolean
  jobs: boolean
}

export interface NudgeResult {
  contact: string
  status: 'sent' | 'failed' | 'skipped' | 'later' | 'would_send'
  channel: 'sms' | 'email' | null
  reason: string
}

export interface NudgeRow {
  id: string
  contact: string
  channel: 'sms' | 'email'
  status: 'queued' | 'sent' | 'failed'
  round: number
  kind: 'stalled' | 'manual'
  at: string
  error: string
}

export interface SyncState {
  enabled: boolean
  state: 'off' | 'not_sent' | 'synced' | 'failing' | 'pending'
  project_id: string | null
  log: { at: string; status: string; detail: string }[]
  result?: { ok: boolean; state: string; message: string; changes: number }
}
