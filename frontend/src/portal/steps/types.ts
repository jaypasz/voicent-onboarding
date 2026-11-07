import type { PortalStep } from '../../api/types'

export interface StepProps {
  step: PortalStep
  /** Send an answer. Resolves when accepted; throws ApiError (with problems) when refused. */
  submit: (data: unknown) => Promise<void>
  busy: boolean
  problems: string[]
}
