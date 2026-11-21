import type { StepStatus } from '../api/types'
import { STEP_STATUS } from '../lib/format'

export interface TrackerStep {
  key: string
  title: string
  status: StepStatus
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
