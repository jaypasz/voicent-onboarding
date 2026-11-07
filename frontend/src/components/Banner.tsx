import type { ReactNode } from 'react'

export function Banner({ kind = 'info', children }: { kind?: 'info' | 'warn' | 'error' | 'ok'; children: ReactNode }) {
  const glyph = { info: 'ℹ', warn: '⚠', error: '✕', ok: '✓' }[kind]
  return (
    <div className={`banner banner-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <span aria-hidden="true">{glyph}</span> <div>{children}</div>
    </div>
  )
}

export function Problems({ problems }: { problems: string[] }) {
  if (!problems.length) return null
  return (
    <Banner kind="error">
      <ul className="problems">
        {problems.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
    </Banner>
  )
}
