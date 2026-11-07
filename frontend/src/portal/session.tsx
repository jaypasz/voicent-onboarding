import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, request, type RequestOptions } from '../api/http'

export type SessionStatus = 'loading' | 'ready' | 'unavailable' | 'busy' | 'error'

export interface PortalApi {
  status: SessionStatus
  /** Calls the portal API with the current session, renewing it once if it has expired. */
  call: <T>(path: string, opts?: RequestOptions) => Promise<T>
}

export const PortalContext = createContext<PortalApi | null>(null)

interface Exchange {
  session: string
  expires_in: number
}

/**
 * A client arrives with a link token in the URL. It is swapped once for a short-lived session that lives only in
 * memory, and renewed shortly before it runs out. A 401 from the server means the link is no longer valid, and the
 * page says so without saying why (it must not reveal whether a link exists).
 */
export function PortalSessionProvider({ linkToken, children }: { linkToken: string; children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const session = useRef<string | null>(null)
  const inflight = useRef<Promise<string> | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fail = useCallback((e: unknown): never => {
    setStatus(e instanceof ApiError && e.status === 401 ? 'unavailable' : e instanceof ApiError && e.status === 429 ? 'busy' : 'error')
    throw e
  }, [])

  const schedule = useCallback((seconds: number, renew: () => void) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(renew, Math.max(10, seconds - 120) * 1000)
  }, [])

  const exchange = useCallback((): Promise<string> => {
    if (inflight.current) return inflight.current
    const p = request<Exchange>('/portal/exchange', { body: { token: linkToken }, token: null })
      .then((r) => {
        session.current = r.session
        setStatus('ready')
        schedule(r.expires_in, () => void exchange().catch(() => {}))
        return r.session
      })
      .catch(fail)
      .finally(() => {
        inflight.current = null
      })
    inflight.current = p
    return p
  }, [linkToken, fail, schedule])

  useEffect(() => {
    void exchange().catch(() => {})
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [exchange])

  const call = useCallback(
    async <T,>(path: string, opts: RequestOptions = {}): Promise<T> => {
      const token = session.current ?? (await exchange())
      try {
        return await request<T>(path, { ...opts, token })
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          const fresh = await exchange() // the session may just have expired; if the link is dead this fails too
          return request<T>(path, { ...opts, token: fresh })
        }
        throw e
      }
    },
    [exchange],
  )

  const value = useMemo(() => ({ status, call }), [status, call])
  return <PortalContext.Provider value={value}>{children}</PortalContext.Provider>
}

export function usePortal(): PortalApi {
  const v = useContext(PortalContext)
  if (!v) throw new Error('usePortal outside PortalSessionProvider')
  return v
}
