// One place that talks to the backend. Errors carry the server's own wording and, for 422s, every problem it listed.

export class ApiError extends Error {
  status: number
  problems: string[]
  retryAfter: number | null

  constructor(status: number, message: string, problems: string[] = [], retryAfter: number | null = null) {
    super(message)
    this.status = status
    this.problems = problems
    this.retryAfter = retryAfter
  }
}

export interface RequestOptions {
  method?: string
  body?: unknown
  token?: string | null
  text?: boolean
}

let adminToken: () => Promise<string | null> = async () => null

/** The admin app registers how to get the signed-in user's token. The client portal passes its own token per call. */
export function setAdminTokenGetter(fn: () => Promise<string | null>) {
  adminToken = fn
}

function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return 'Some of what was sent is not valid.'
  return 'Something went wrong.'
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const token = opts.token === undefined ? await adminToken() : opts.token
  if (token) headers.Authorization = `Bearer ${token}`
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method: opts.method ?? (opts.body !== undefined ? 'POST' : 'GET'),
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    })
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.")
  }
  if (!res.ok) {
    let detail: unknown = null
    let problems: string[] = []
    try {
      const j = await res.json()
      detail = j.detail
      if (Array.isArray(j.problems)) problems = j.problems.map(String)
    } catch {
      /* not JSON */
    }
    const ra = res.headers.get('Retry-After')
    throw new ApiError(res.status, detailText(detail), problems, ra ? Number(ra) : null)
  }
  if (opts.text) return (await res.text()) as T
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
