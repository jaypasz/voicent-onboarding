import { useState } from 'react'
import { ApiError } from '../api/http'
import type { PortalStep } from '../api/types'
import { StepBadge } from '../components/StatusBadge'
import { dueLabel } from '../lib/format'
import Comments from './Comments'
import { usePortal } from './session'
import { rendererFor } from './steps/registry'

export default function StepPanel({ step, onChanged, onSaved, onboardingStatus, hideMeta = false }: { step: PortalStep; onChanged: () => Promise<unknown>; onSaved?: () => void; onboardingStatus: string; hideMeta?: boolean }) {
  const { call } = usePortal()
  const [busy, setBusy] = useState(false)
  const [problems, setProblems] = useState<string[]>([])
  const Renderer = rendererFor(step.type)
  const due = dueLabel(step.due_at, step.status)

  async function submit(data: unknown) {
    setBusy(true)
    setProblems([])
    try {
      await call(`/portal/steps/${step.key}`, { method: 'PUT', body: { data } })
      await onChanged()
      onSaved?.()
    } catch (e) {
      setProblems(e instanceof ApiError ? (e.problems.length ? e.problems : [e.message]) : ['That did not save. Please try again.'])
      throw e
    } finally {
      setBusy(false)
    }
  }

  const notYours = step.assignee && !step.assignee.is_you
  return (
    <div className="step-panel">
      {!hideMeta && (
        <div className="step-head">
          <StepBadge status={step.status} />
          {due && <span className={due.overdue ? 'due due-overdue' : 'due'}>{due.overdue ? '⚠ ' : ''}{due.text}</span>}
          {step.assignee && <span className="due">{step.assignee.is_you ? 'For you' : `For ${step.assignee.name}`}</span>}
        </div>
      )}
      {step.description && <p>{step.description}</p>}
      {!step.can_write && (
        <p className="help" role="note">
          {onboardingStatus !== 'active' ? 'Changes are switched off for now.' : notYours ? `This step is for ${step.assignee!.name}. You can read it here.` : 'You can read this step here.'}
        </p>
      )}
      <Renderer step={step} submit={submit} busy={busy} problems={problems} />
      <Comments stepKey={step.key} comments={step.comments} canWrite={step.can_write} onChanged={onChanged} />
    </div>
  )
}
