import type { FormField } from '../api/types'

/** The server lists problems as "Label: message". Match them back to the fields they are about. */
export function problemsByField(problems: string[], fields: FormField[]): { byKey: Record<string, string>; rest: string[] } {
  const byKey: Record<string, string> = {}
  const rest: string[] = []
  for (const p of problems) {
    const f = fields.find((x) => p.startsWith(`${x.label}:`))
    if (f && !byKey[f.key]) byKey[f.key] = p.slice(f.label.length + 1).trim()
    else rest.push(p)
  }
  return { byKey, rest }
}
