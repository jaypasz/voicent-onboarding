import { useState, type FormEvent } from 'react'
import { useCancelInvite, useChangeMember, useInvite, useRemoveMember, useTeam, useUpdateMe } from '../api/admin'
import { ApiError } from '../api/http'
import { Banner } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { ROLE_LABEL, memberLabel } from '../lib/team'

const ROLES = ['admin', 'manager', 'member', 'viewer'] as const

/** Who is on the team and what each can do. A linked org's team comes from Voicent-App; others invite by email. */
export default function TeamPage() {
  const team = useTeam()
  const invite = useInvite()
  const cancel = useCancelInvite()
  const change = useChangeMember()
  const remove = useRemoveMember()
  const updateMe = useUpdateMe()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('member')
  const [error, setError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setError(null); setOk(null)
    try { await fn(); if (done) setOk(done) } catch (e) { setError(e instanceof ApiError ? e.message : 'That did not work.') }
  }

  if (team.isError) return <LoadError error={team.error} what="the team" />
  if (!team.data) return <p>Loading…</p>
  const t = team.data
  const me = t.members.find((m) => m.is_you)

  async function submit(e: FormEvent) {
    e.preventDefault()
    await run(async () => { await invite.mutateAsync({ email: email.trim(), role }); setEmail('') }, `Invited. They join when they sign in as ${email.trim()}.`)
  }

  return (
    <div className="stack">
      <h1>Team</h1>
      {t.linked && <Banner>Your team comes from Voicent-App: add people and change their roles there. Everyone listed can be given onboardings and steps, even before they first sign in here.</Banner>}
      {t.linked && !t.in_sync && <Banner kind="warn">Voicent-App couldn't be reached just now, so this is the team as it was last copied.</Banner>}
      {error && <Banner kind="error">{error}</Banner>}
      {ok && <Banner kind="ok">{ok}</Banner>}

      <ul className="cards" aria-label="Team members">
        {t.members.map((m) => (
          <li key={m.id} className="card row between wrap">
            <div>
              <strong>{memberLabel(m)}</strong>{m.is_you && <span className="help"> · you</span>}
              <div className="help">{m.name ? `${m.email} · ` : ''}{ROLE_LABEL[m.role] ?? m.role}</div>
            </div>
            {t.can_manage && m.source === 'local' && (
              <div className="row wrap">
                <label className="field-group"><span className="sr-only">Role for {memberLabel(m)}</span>
                  <select value={m.role} onChange={(e) => void run(() => change.mutateAsync({ id: m.id, role: e.target.value }), 'Role changed.')}>
                    {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                  </select>
                </label>
                <button className="btn btn-small" onClick={() => window.confirm(`Remove ${memberLabel(m)} from the team? They lose access at once.`) && void run(() => remove.mutateAsync(m.id), 'Removed.')}>Remove</button>
              </div>
            )}
          </li>
        ))}
      </ul>

      {t.can_manage && (
        <section className="card stack" aria-labelledby="invite-h">
          <h2 id="invite-h">Invite someone</h2>
          <form className="row wrap" onSubmit={submit}>
            <label className="field-group grow"><span>Their email</span><input type="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} maxLength={200} /></label>
            <label className="field-group"><span>Role</span>
              <select value={role} onChange={(e) => setRole(e.target.value)}>{ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select>
            </label>
            <button className="btn btn-primary" disabled={!email.trim() || invite.isPending}>Invite</button>
          </form>
          <p className="help">Nothing is sent: tell them to sign in with that address. They join the moment they do.</p>
          {t.invites.length > 0 && (
            <ul className="cards" aria-label="Waiting to join">
              {t.invites.map((i) => (
                <li key={i.id} className="card row between wrap">
                  <div>{i.email} <span className="help">· {ROLE_LABEL[i.role] ?? i.role} · waiting to sign in</span></div>
                  <button className="btn btn-small" onClick={() => void run(() => cancel.mutateAsync(i.id), 'Invite cancelled.')}>Cancel</button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {me && (
        <section className="card stack" aria-labelledby="me-h">
          <h2 id="me-h">Your notifications</h2>
          <label className="check">
            <input type="checkbox" checked={!!me.notify_email} onChange={(e) => void run(() => updateMe.mutateAsync({ notify_email: e.target.checked }), 'Saved.')} />
            Also email me when I'm given something, a client answers a step I follow up, or an onboarding I look after finishes or goes quiet
          </label>
          <p className="help">They always show under Notifications here. Emails never include what a client typed.</p>
        </section>
      )}
    </div>
  )
}
