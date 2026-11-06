import { useEffect, useState } from 'react'

type Health = 'checking' | 'up' | 'down'

// Phase 1 shell: proves the build, the /api proxy and the server are wired together.
// The client portal (/c/:token) and the admin app arrive in later phases.
export default function App() {
  const [health, setHealth] = useState<Health>('checking')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => setHealth(r.ok ? 'up' : 'down'))
      .catch(() => setHealth('down'))
  }, [])

  return (
    <main style={{ maxWidth: 560, margin: '4rem auto', padding: '0 1rem', fontFamily: 'system-ui, sans-serif' }}>
      <h1>Voicent Onboarding</h1>
      <p>
        Server: {health === 'checking' ? 'checking…' : health === 'up' ? '✓ up' : '✗ not reachable'}
      </p>
    </main>
  )
}
