import type { TemplateDoc } from '../builder/doc'
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
  /** Whose portal this is. A reseller's clients see the reseller, never Voicent. */
  brand?: Brand
}

export interface Brand {
  name: string
  logo_url: string | null
  primary_color: string | null
  accent_color: string | null
}

/** The admin's read-only view of what a client sees. */
export interface PreviewView extends PortalView {
  preview: true
  contacts: { id: string; name: string; role: string }[]
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
  /** Set when marked as a paying customer. Only paying clients get a Voicent workspace. */
  paying_since: string | null
  /** Jay's call that a prospect is lost or has gone quiet. Every other stage is worked out by the server. */
  outcome: 'lost' | 'stalled' | null
  stage: Stage
  contacts: Contact[]
}

export type Stage = 'lead' | 'onboarding' | 'won' | 'lost' | 'stalled'

export interface Task {
  id: string
  client_id: string
  onboarding_id: string | null
  title: string
  assignee_id: string | null
  due_on: string | null
  done_at: string | null
  created_at: string
}

export interface TemplateSummary {
  id: string
  name: string
  slug: string
  current_version: number
  archived: boolean
}

export interface TemplateDetail extends TemplateSummary {
  document: TemplateDoc
  versions: number[]
  new_version?: boolean
}

export type Attention = 'nudges_exhausted' | 'unreachable' | null
export type ProvisionState = 'pending' | 'delivered' | 'failed' | null

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
  provision_state: ProvisionState
  /** The team member who looks after it. */
  owner_member_id?: string | null
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
  /** Who on our side follows this step up. Never shown to the client. */
  team_assignee_id?: string | null
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
  provisioning: boolean
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

export interface ProvisionStatus {
  enabled: boolean
  wanted: boolean
  /** unpaid: finished, but a workspace is only asked for once the client is marked as paying. */
  state: 'not_wanted' | 'off' | 'waiting' | 'unpaid' | 'pending' | 'delivered' | 'failed'
  workspace_id: string | null
  client_id: string
  paying: boolean
  attempts: number
  next_attempt_at: string | null
  delivered_at: string | null
  error: string
  log: { at: string; status: string; detail: string }[]
  result?: { ok: boolean; state: string; message: string }
}

/** An onboarding's own copy of its template, for the step builder. */
export interface OnboardingDocument {
  document: TemplateDoc
  /** False only for an archived onboarding. */
  editable: boolean
  /** Already sent to the client: saved changes are live at once. */
  sent: boolean
  locked: string[]
  /** Which version of the steps this screen is looking at; sent back so a stale save is refused. */
  etag: string
}

export interface TemplateCheck {
  ok: boolean
  problems: string[]
}

export type Role = 'admin' | 'manager' | 'member' | 'viewer'

export interface OrgChoice {
  id: string
  name: string
  account_type: 'direct' | 'reseller'
  role: Role
}

export interface Me {
  id: string
  email: string
  kind: 'user' | 'service' | 'local'
  superuser: boolean
  orgs: OrgChoice[]
}

export interface OrgSettings {
  id: string
  name: string
  slug: string
  account_type: 'direct' | 'reseller'
  /** Linked to a Voicent tenant: logo and colours are set in Voicent-App, not here. */
  linked: boolean
  role: Role
  brand: Brand
  logo_url: string | null
  brand_name: string
  email_from_name: string
  reply_to_email: string
  sms_from: string
  email_from_preview: string | null
}

export interface TeamMember {
  id: string
  email: string
  name: string
  role: Role
  source: 'voicent' | 'local'
  is_you: boolean
  notify_email: boolean | null
}

export interface Team {
  /** Linked to a Voicent tenant: people and roles come from Voicent-App. */
  linked: boolean
  in_sync: boolean
  can_manage: boolean
  me: string | null
  members: TeamMember[]
  invites: { id: string; email: string; role: Role; invited_by: string; created_at: string }[]
}

export interface AppNotification {
  id: string
  kind: string
  text: string
  onboarding_id: string | null
  step_key: string
  read: boolean
  created_at: string
}
