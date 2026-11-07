import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

/** Without these two the admin app runs in local mode: no login, and the backend must be running with AUTH_DISABLED=1. */
export const supabase = url && key ? createClient(url, key) : null
export const localMode = supabase === null
