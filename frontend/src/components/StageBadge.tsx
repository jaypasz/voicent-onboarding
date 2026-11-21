import type { Stage } from '../api/types'
import { STAGE } from '../lib/format'

/** A glyph and a word, so colour never carries the stage alone. */
export function StageBadge({ stage }: { stage: Stage }) {
  const { glyph, label, help } = STAGE[stage]
  const tone = stage === 'won' ? 'badge-done' : stage === 'onboarding' || stage === 'stalled' ? 'badge-in_progress' : ''
  return <span className={`badge ${tone}`} title={help}><span aria-hidden="true">{glyph}</span> {label}</span>
}
