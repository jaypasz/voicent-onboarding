/** Links come from templates, so only plain https goes into an href. Anything else is shown as text, never as a link. */
export function safeHttpsUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const u = new URL(value)
    return u.protocol === 'https:' && u.hostname ? u.toString() : null
  } catch {
    return null
  }
}
