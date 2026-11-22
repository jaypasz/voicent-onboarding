import type { PortalStageState, StageState, StepStatus } from '../api/types'
import { STAGE_STATE, STEP_STATUS } from '../lib/format'

export interface TrackerStep {
  key: string
  title: string
  status: StepStatus
}

export interface TrackerStage {
  key: string
  title: string
  state: StageState | PortalStageState
  /** A line under the title: "2 of 5 done", a date range. */
  detail?: string
}

/**
 * Every step in order along one line. Colour never carries meaning alone: each node has a glyph and the
 * status is also spoken. The first step still to do is marked "Next". It scrolls sideways on a narrow screen.
 */
export function StepTracker({ steps, label = 'Steps' }: { steps: TrackerStep[]; label?: string }) {
  if (steps.length === 0) return null
  const next = steps.findIndex((s) => s.status === 'pending' || s.status === 'in_progress')
  return (
    <ol className="tracker" aria-label={label}>
      {steps.map((s, i) => {
        const { glyph, label: word } = STEP_STATUS[s.status]
        const isNext = i === next
        return (
          <li key={s.key} className={`tracker-step tracker-${s.status}${isNext ? ' tracker-next' : ''}`} aria-current={isNext ? 'step' : undefined}>
            <span className="tracker-node" aria-hidden="true">{glyph}</span>
            <span className="tracker-title">{s.title}</span>
            <span className="visually-hidden">{`${word}${isNext ? ', next' : ''}`}</span>
          </li>
        )
      })}
    </ol>
  )
}

const FINISHED: (StageState | PortalStageState)[] = ['signed_off', 'done']
const CLASS: Record<StageState | PortalStageState, string> = { locked: 'locked', open: 'in_progress', ready: 'ready', waiting: 'ready', signed_off: 'done', done: 'done' }

/** The stages along one line, each with its state in a glyph and in words. The first stage not yet finished is "Current". */
export function StageTracker({ stages, label = 'Stages' }: { stages: TrackerStage[]; label?: string }) {
  if (stages.length === 0) return null
  const current = stages.findIndex((s) => !FINISHED.includes(s.state))
  return (
    <ol className="tracker tracker-stages" aria-label={label}>
      {stages.map((s, i) => {
        const { glyph, label: word } = STAGE_STATE[s.state]
        const isCurrent = i === current
        return (
          <li key={s.key} className={`tracker-step tracker-${CLASS[s.state]}${isCurrent ? ' tracker-next' : ''}`} aria-current={isCurrent ? 'step' : undefined}>
            <span className="tracker-node" aria-hidden="true">{glyph}</span>
            <span className="tracker-title">{s.title}</span>
            <span className="tracker-detail">{word}{s.detail ? ` · ${s.detail}` : ''}</span>
          </li>
        )
      })}
    </ol>
  )
}
