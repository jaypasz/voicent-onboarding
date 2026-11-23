import { Problems } from '../../components/Banner'
import { Embed, isVideo } from '../../components/Embed'
import type { StepProps } from './types'

export default function InfoVideoStep({ step, submit, busy, problems }: StepProps) {
  const media = step.media
  const seen = step.response?.seen === true
  const video = isVideo(media)
  return (
    <div className="stack">
      {step.config.instructions && <p style={{ whiteSpace: 'pre-wrap' }}>{step.config.instructions}</p>}
      {media ? <Embed info={media} title={step.title} /> : <p className="help">This isn't available right now. Tell us in the comments and we'll send it another way.</p>}
      <Problems problems={problems} />
      {seen ? (
        <p className="help">✓ {video ? 'Watched' : 'Read'}. Thanks.</p>
      ) : step.can_write && (
        <button className="btn btn-primary btn-big" disabled={busy} onClick={() => void submit({ seen: true }).catch(() => {})}>
          {busy ? 'Saving…' : video ? "I've watched it" : "I've read it"}
        </button>
      )}
    </div>
  )
}
