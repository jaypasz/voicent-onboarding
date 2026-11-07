import type { Session } from '@supabase/supabase-js'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setAdminTokenGetter } from '../api/http'
import { localMode, supabase } from './supabase'

interface AuthState {
  ready: boolean
  signedIn: boolean
  email: string
  signIn: (email: string, password: string) => Promise<string | null>
  signOut: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [ready, setReady] = useState(localMode)

  useEffect(() => {
    if (!supabase) return
    setAdminTokenGetter(async () => (await supabase!.auth.getSession()).data.session?.access_token ?? null)
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setReady(true)
    })
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s))
    return () => data.subscription.unsubscribe()
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      ready,
      signedIn: localMode || session !== null,
      email: localMode ? 'local mode' : (session?.user.email ?? ''),
      signIn: async (email, password) => {
        if (!supabase) return null
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        return error ? "That email and password didn't work." : null
      },
      signOut: async () => {
        await supabase?.auth.signOut()
      },
    }),
    [ready, session],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}
