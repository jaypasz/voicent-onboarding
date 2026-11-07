import { useEffect, useState } from 'react'
import type { PortalView } from '../api/types'
import { Banner } from '../components/Banner'
import { STEP_STATUS } from '../lib/format'
import StepPanel from './StepPanel'

const open = (s: { status: string; can_write: boolean }) => s.can_write && s.status !== 'done' && s.status !== 'skipped'

/** The first step to work on after `from`, wrapping round. -1 when everything the client can do is done. */
export function nextOpenIndex(steps: { status: string; can_write: boolean }[], from: number): number {
  for (let i = from + 1; i < steps.length; i++) if (open(steps[i])) return i
  return steps.findIndex(open)
}

/** One step per screen, for a phone. After a step is saved the next open one comes up by itself. */
export default function FocusLayout({ view, onChanged }: { view: PortalView; onChanged: () => Promise<unknown> }) {
  const steps = view.steps
  const [index, setIndex] = useState(() => Math.max(0, nextOpenIndex(steps, -1)))
  const [advance, setAdvance] = useState(false)
  const [reviewing, setReviewing] = useState(false)

  useEffect(() => {
    if (!advance) return
    setAdvance(false)
    const next = nextOpenIndex(steps, index)
    if (next === -1) setReviewing(false)
    else setIndex(next)
  }, [advance, steps, index])

  const allDone = nextOpenIndex(steps, -1) === -1 && view.status !== 'paused'
  if (allDone && !reviewing) {
    return (
      <div className="stack center">
        <Banner kind="ok">
          <strong>That's everything we need from you.</strong> Thank you, {view.contact.name.split(' ')[0]}. We'll take it from here and be in touch.
        </Banner>
        <button className="btn btn-big" onClick={() => { setIndex(0); setReviewing(true) }}>
          Review or change your answers
        </button>
      </div>
    )
  }
  if (!steps.length) return <Banner>There is nothing for you to do here yet.</Banner>

  const step = steps[Math.min(index, steps.length - 1)]
  return (
    <div className="stack">
      <nav aria-label="Steps" className="dots">
        {steps.map((s, i) => (
          <button
            key={s.key}
            className={`dot dot-${s.status}${i === index ? ' dot-current' : ''}`}
            aria-label={`Step ${i + 1} of ${steps.length}: ${s.title}, ${STEP_STATUS[s.status].label}`}
            aria-current={i === index ? 'step' : undefined}
            onClick={() => setIndex(i)}
          >
            <span aria-hidden="true">{STEP_STATUS[s.status].glyph}</span>
          </button>
        ))}
      </nav>
      <h2 className="step-title">
        <span className="step-count">
          Step {index + 1} of {steps.length}
        </span>
        {step.title}
      </h2>
      <StepPanel key={step.key} step={step} onChanged={onChanged} onSaved={() => setAdvance(true)} onboardingStatus={view.status} />
      <div className="row between">
        <button className="btn" disabled={index === 0} onClick={() => setIndex(index - 1)}>
          ← Back
        </button>
        <button className="btn" disabled={index === steps.length - 1} onClick={() => setIndex(index + 1)}>
          {step.status === 'done' ? 'Next →' : 'Skip for now →'}
        </button>
      </div>
    </div>
  )
}
