import { useRef, useState } from 'react'
import { ApiError } from '../../api/http'
import { Banner, Problems } from '../../components/Banner'
import { formatBytes } from '../../lib/format'
import { UPLOAD_TYPES, extensionOf, fileProblem, putToSignedUrl } from '../../lib/uploads'
import { usePortal } from '../session'
import type { StepProps } from './types'

interface UploadUrl {
  file_id: string
  upload_url: string
}

export default function UploadStep({ step, submit, busy, problems }: StepProps) {
  const { call } = usePortal()
  const input = useRef<HTMLInputElement>(null)
  const accept = (step.config.accept ?? []) as string[]
  const maxMb = (step.config.max_mb ?? 10) as number
  const minFiles = (step.config.min_files ?? 1) as number
  const maxFiles = (step.config.max_files ?? 5) as number
  const [working, setWorking] = useState(false)
  const [progress, setProgress] = useState<Record<string, number>>({})
  const [errors, setErrors] = useState<string[]>([])
  const saved = ((step.response?.file_ids ?? []) as string[]).map((id) => step.files.find((f) => f.id === id)).filter(Boolean)

  async function upload(files: File[]) {
    setErrors([])
    if (files.length > maxFiles) return setErrors([`You can add up to ${maxFiles} file${maxFiles === 1 ? '' : 's'} here.`])
    const bad = files.map((f) => fileProblem(f, accept, maxMb)).filter(Boolean) as string[]
    if (bad.length) return setErrors(bad)
    setWorking(true)
    try {
      const ids: string[] = []
      for (const f of files) {
        const target = await call<UploadUrl>(`/portal/steps/${step.key}/upload-url`, {
          body: { name: f.name, size: f.size, content_type: UPLOAD_TYPES[extensionOf(f.name)] },
        })
        await putToSignedUrl(target.upload_url, f, (p) => setProgress((s) => ({ ...s, [f.name]: p })))
        ids.push(target.file_id)
      }
      await submit({ file_ids: ids })
    } catch (e) {
      setErrors(e instanceof ApiError ? [e.message, ...e.problems] : [e instanceof Error ? e.message : 'The upload failed.'])
    } finally {
      setWorking(false)
      setProgress({})
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="stack">
      {step.config.prompt && <p>{step.config.prompt}</p>}
      <p className="help">
        Allowed: {accept.join(', ')}. Up to {maxMb} MB each{maxFiles > 1 ? `, up to ${maxFiles} files` : ''}.
      </p>
      <Problems problems={[...errors, ...problems]} />
      {saved.length > 0 && (
        <ul className="files" aria-label="Files you added">
          {saved.map((f) => (
            <li key={f!.id}>
              <span aria-hidden="true">✓</span> {f!.name} <span className="help">({formatBytes(f!.size)})</span>
            </li>
          ))}
        </ul>
      )}
      {working && (
        <div role="status">
          {Object.entries(progress).map(([name, p]) => (
            <div key={name}>
              Uploading {name}: {Math.round(p * 100)}%
            </div>
          ))}
          {Object.keys(progress).length === 0 && <div>Preparing upload…</div>}
        </div>
      )}
      {step.can_write ? (
        <>
          <label className="btn btn-primary btn-big file-pick">
            {saved.length ? 'Replace files' : maxFiles > 1 ? 'Choose files' : 'Choose a file'}
            <input
              ref={input}
              type="file"
              hidden
              multiple={maxFiles > 1}
              accept={accept.map((e) => `.${e}`).join(',')}
              disabled={working || busy}
              onChange={(e) => void upload(Array.from(e.target.files ?? []))}
            />
          </label>
          {minFiles === 0 && saved.length === 0 && (
            <button type="button" className="btn btn-big" disabled={working || busy} onClick={() => void submit({ file_ids: [] }).catch(() => {})}>
              I have nothing to add
            </button>
          )}
        </>
      ) : (
        saved.length === 0 && <Banner>No files yet.</Banner>
      )}
    </div>
  )
}
