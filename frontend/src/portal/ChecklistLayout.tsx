import { useState } from 'react'
import type { PortalStep, PortalView } from '../api/types'
import { StepBadge } from '../components/StatusBadge'
import { dueLabel } from '../lib/format'
import StepPanel from './StepPanel'

function groups(view: PortalView): { key: string; title: string; steps: PortalStep[] }[] {
  const out = view.sections.map((s) => ({ key: s.key, title: s.title, steps: view.steps.filter((x) => x.section === s.key) }))
  const loose = view.steps.filter((x) => !view.sections.some((s) => s.key === x.section))
  if (loose.length) out.push({ key: '_', title: out.length ? 'Other' : 'Steps', steps: loose })
  return out.filter((g) => g.steps.length)
}

/** Everything on one page: sections, who each step is for, what is due. For an agency or MSP with several people involved. */
export default function ChecklistLayout({ view, onChanged }: { view: PortalView; onChanged: () => Promise<unknown> }) {
  const firstOpen = view.steps.find((s) => s.can_write && s.status !== 'done' && s.status !== 'skipped')?.key
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(firstOpen ? [firstOpen] : []))
  const toggle = (k: string) => setExpanded((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })

  return (
    <div className="stack">
      {groups(view).map((g) => {
        const done = g.steps.filter((s) => s.status === 'done').length
        return (
          <section key={g.key} aria-labelledby={`sec-${g.key}`} className="section">
            <h2 id={`sec-${g.key}`}>
              {g.title} <span className="help">({done} of {g.steps.length} done)</span>
            </h2>
            <ul className="steps">
              {g.steps.map((s) => {
                const isOpen = expanded.has(s.key)
                const due = dueLabel(s.due_at, s.status)
                return (
                  <li key={s.key} className={`step step-${s.status}`}>
                    <button className="step-toggle" aria-expanded={isOpen} aria-controls={`panel-${s.key}`} onClick={() => toggle(s.key)}>
                      <span className="step-toggle-title">{s.title}</span>
                      <span className="step-toggle-meta">
                        <StepBadge status={s.status} />
                        {s.assignee && <span className="due">{s.assignee.is_you ? 'For you' : `For ${s.assignee.name}`}</span>}
                        {due && <span className={due.overdue ? 'due due-overdue' : 'due'}>{due.overdue ? '⚠ ' : ''}{due.text}</span>}
                      </span>
                      <span aria-hidden="true" className="chev">{isOpen ? '▾' : '▸'}</span>
                    </button>
                    {isOpen && (
                      <div id={`panel-${s.key}`}>
                        <StepPanel step={s} onChanged={onChanged} onboardingStatus={view.status} hideMeta />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
