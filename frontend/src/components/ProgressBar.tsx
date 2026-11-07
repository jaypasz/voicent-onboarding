import type { Progress } from '../api/types'

export function ProgressBar({ progress, label = 'Progress' }: { progress: Progress; label?: string }) {
  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0
  return (
    <div className="progress">
      <div className="progress-text">
        {label}: {progress.done} of {progress.total} done
      </div>
      <div className="progress-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={progress.total} aria-valuenow={progress.done}>
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
