import { ApiError } from '../api/http'
import { useAuthMaybe } from '../auth/AuthContext'
import { localMode as buildIsLocal } from '../auth/supabase'
import { Banner } from './Banner'

export interface Diagnosis {
  title: string
  steps: string[]
}

/**
 * Turns "it didn't load" into what is actually wrong and what to do about it. This screen is only ever seen by the
 * person who runs the app, so it names the settings. (The client portal has its own, deliberately vague, messages.)
 */
export function diagnose(error: unknown, ctx: { localMode: boolean; userId?: string }): Diagnosis {
  const status = error instanceof ApiError ? error.status : -1
  const detail = error instanceof ApiError ? error.message : ''
  if (status === 401 && ctx.localMode) {
    return {
      title: "This site was built without sign-in settings, so the server won't talk to it.",
      steps: [
        'In Railway, set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY on this service.',
        'Redeploy. They are baked in when the site is built, so a restart is not enough.',
        'The top right of this page says "local mode" until that is fixed.',
      ],
    }
  }
  if (status === 401) {
    return {
      title: "You're signed in, but the server didn't accept your sign-in.",
      steps: [
        'On Railway, check SUPABASE_JWKS_URL is https://<your-project>.supabase.co/auth/v1/.well-known/jwks.json for the same Supabase project as VITE_SUPABASE_URL.',
        'If your project still uses the legacy secret instead, set SUPABASE_JWT_SECRET.',
        'If it worked before, your session may have expired: sign out and back in.',
      ],
    }
  }
  if (status === 403) {
    const id = ctx.userId || '<your user id from Supabase, Authentication > Users>'
    return {
      title: "You're signed in, but this account isn't linked to an organization yet.",
      steps: [
        `Run this once against the production database: python -m app.cli seed --org-name Voicent --org-slug voicent --admin-user-id ${id} --admin-email <your email>`,
        'It is safe to run twice. Then reload this page.',
      ],
    }
  }
  if (status === 400 && /X-Org-Id/.test(detail)) {
    return { title: 'More than one organization matched.', steps: ['This account belongs to several organizations and the app does not choose between them yet.'] }
  }
  if (status === 0) {
    return { title: "The server didn't answer.", steps: ['Check your connection, then reload.', 'If it keeps happening, look at the service in Railway: it may be restarting.'] }
  }
  if (status >= 500) {
    return {
      title: `The server hit a problem (status ${status}).`,
      steps: [
        'Open the deploy logs in Railway and look for the error just after this request.',
        'The usual cause is the database: a wrong DATABASE_URL, or migrations that did not finish (the service runs them when it starts).',
      ],
    }
  }
  return { title: detail || 'Something went wrong.', steps: status > 0 ? [`The server answered with status ${status}.`] : [] }
}

export function LoadError({ error, what }: { error: unknown; what: string }) {
  const auth = useAuthMaybe()
  const d = diagnose(error, { localMode: buildIsLocal, userId: auth?.userId })
  return (
    <Banner kind="error">
      <strong>Couldn't load {what}.</strong> {d.title}
      {d.steps.length > 0 && (
        <ul className="problems">
          {d.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}
    </Banner>
  )
}
