import type { ComponentType } from 'react'
import ApprovalStep from './ApprovalStep'
import BookCallStep from './BookCallStep'
import ConnectStep from './ConnectStep'
import FormStep from './FormStep'
import UploadStep from './UploadStep'
import type { StepProps } from './types'

// One renderer per step type. Mirrors the backend registry; internal tasks never reach the portal, so they have none.
const RENDERERS: Record<string, ComponentType<StepProps>> = {
  form: FormStep,
  upload: UploadStep,
  connect: ConnectStep,
  book_call: BookCallStep,
  approval: ApprovalStep,
}

export function rendererFor(type: string): ComponentType<StepProps> {
  return RENDERERS[type] ?? Unsupported
}

function Unsupported() {
  return <p className="help">This step can't be shown here yet. Please tell us in the comments and we'll help.</p>
}
