import type { OnboardingStatus, StepStatus } from '../api/types'
import { ONBOARDING_STATUS, STEP_STATUS } from '../lib/format'

export function StepBadge({ status }: { status: StepStatus }) {
  const s = STEP_STATUS[status] ?? STEP_STATUS.pending
  return (
    <span className={`badge badge-${status}`}>
      <span aria-hidden="true">{s.glyph}</span> {s.label}
    </span>
  )
}

export function OnboardingBadge({ status }: { status: OnboardingStatus }) {
  const s = ONBOARDING_STATUS[status] ?? ONBOARDING_STATUS.draft
  return (
    <span className={`badge badge-ob-${status}`}>
      <span aria-hidden="true">{s.glyph}</span> {s.label}
    </span>
  )
}
