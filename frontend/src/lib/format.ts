import type { OnboardingStatus, PortalStageState, Stage, StageState, StepStatus } from '../api/types'

// Colour never carries meaning alone: every status has a glyph and a word.
export const STEP_STATUS: Record<StepStatus, { glyph: string; label: string }> = {
  pending: { glyph: '○', label: 'To do' },
  in_progress: { glyph: '◐', label: 'In progress' },
  done: { glyph: '✓', label: 'Done' },
  skipped: { glyph: '–', label: 'Skipped' },
}

export const ONBOARDING_STATUS: Record<OnboardingStatus, { glyph: string; label: string }> = {
  draft: { glyph: '✎', label: 'Draft' },
  active: { glyph: '●', label: 'Active' },
  paused: { glyph: '⏸', label: 'Paused' },
  completed: { glyph: '✓', label: 'Completed' },
  archived: { glyph: '▣', label: 'Archived' },
}

export const STAGES: Stage[] = ['lead', 'onboarding', 'won', 'lost', 'stalled']
export const STAGE: Record<Stage, { glyph: string; label: string; help: string }> = {
  lead: { glyph: '○', label: 'Lead', help: 'No onboarding under way yet.' },
  onboarding: { glyph: '◐', label: 'Onboarding', help: 'An onboarding is active or paused.' },
  won: { glyph: '✓', label: 'Won', help: 'Marked as a paying customer.' },
  lost: { glyph: '✕', label: 'Lost', help: 'Marked lost.' },
  stalled: { glyph: '⏸', label: 'Stalled', help: 'Marked stalled: gone quiet.' },
}

/** A date with no time ("2026-12-01"), shown as that day wherever you are. new Date() would read it as UTC midnight and show the day before in the Americas. */
export function formatDay(day: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day ?? '')
  if (!m) return ''
  return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

/** Today's date where you are, as YYYY-MM-DD (toISOString would give the UTC date). */
export function todayLocal(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

/** "Dec 1 – Dec 3, 2026", or just the end, or just the start. */
export function dayRange(start: string | null | undefined, end: string | null | undefined): string {
  if (start && end) return start === end ? formatDay(end) : `${formatDay(start)} – ${formatDay(end)}`
  if (end) return `Due ${formatDay(end)}`
  if (start) return `Starts ${formatDay(start)}`
  return ''
}

/** Every stage state has a glyph and a word, as colour never carries meaning alone. */
export const STAGE_STATE: Record<StageState | PortalStageState, { glyph: string; label: string }> = {
  locked: { glyph: '🔒', label: 'Not open yet' },
  open: { glyph: '◐', label: 'In progress' },
  ready: { glyph: '⏳', label: 'Ready for sign-off' },
  waiting: { glyph: '⏳', label: 'With us for review' },
  signed_off: { glyph: '✓', label: 'Signed off' },
  done: { glyph: '✓', label: 'Done' },
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** "Due Nov 12" or "Overdue since Nov 5". Empty when there is no date or the step is finished. */
/** `day` is the due day where the client is (YYYY-MM-DD), when known: it is what is shown, whatever the browser's time zone. */
export function dueLabel(due: string | null, status: StepStatus, now = new Date(), day?: string | null): { text: string; overdue: boolean } | null {
  if (!due || status === 'done' || status === 'skipped') return null
  const d = new Date(due)
  if (Number.isNaN(d.getTime())) return null
  const overdue = d.getTime() < now.getTime()
  const shown = day ? formatDay(day) : formatDate(due)
  return { text: overdue ? `Overdue since ${shown}` : `Due ${shown}`, overdue }
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function timeAgo(iso: string, now = new Date()): string {
  const s = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}
