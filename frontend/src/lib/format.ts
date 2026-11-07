import type { OnboardingStatus, StepStatus } from '../api/types'

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

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** "Due Nov 12" or "Overdue since Nov 5". Empty when there is no date or the step is finished. */
export function dueLabel(due: string | null, status: StepStatus, now = new Date()): { text: string; overdue: boolean } | null {
  if (!due || status === 'done' || status === 'skipped') return null
  const d = new Date(due)
  if (Number.isNaN(d.getTime())) return null
  const overdue = d.getTime() < now.getTime()
  return { text: overdue ? `Overdue since ${formatDate(due)}` : `Due ${formatDate(due)}`, overdue }
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
