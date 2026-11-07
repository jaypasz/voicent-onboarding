import { useState } from 'react'

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
    } catch {
      setState('failed')
    }
    setTimeout(() => setState('idle'), 2000)
  }
  return (
    <button type="button" className="btn btn-small" onClick={copy}>
      {state === 'copied' ? '✓ Copied' : state === 'failed' ? 'Select and copy it by hand' : label}
    </button>
  )
}
