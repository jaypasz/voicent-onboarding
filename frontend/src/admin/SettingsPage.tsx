import { useEffect, useState } from 'react'
import { useOrgSettings, useSaveOrgSettings, type OrgSettingsPatch } from '../api/admin'
import { ApiError } from '../api/http'
import type { OrgSettings } from '../api/types'
import { Banner, Problems } from '../components/Banner'
import { LoadError } from '../components/LoadError'
import { brandStyle, safeLogo } from '../lib/brand'

type Form = { brand_name: string; email_from_name: string; reply_to_email: string; sms_from: string; logo_url: string; primary_color: string; accent_color: string }

const fromOrg = (o: OrgSettings): Form => ({
  brand_name: o.brand_name, email_from_name: o.email_from_name, reply_to_email: o.reply_to_email, sms_from: o.sms_from,
  logo_url: o.logo_url ?? '', primary_color: o.brand.primary_color ?? '', accent_color: o.brand.accent_color ?? '',
})

/** The organization's brand (what its clients see) and the senders that reach them. Only admins change it. */
export default function SettingsPage() {
  const org = useOrgSettings()
  const save = useSaveOrgSettings()
  const [form, setForm] = useState<Form | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [ok, setOk] = useState(false)

  useEffect(() => { if (org.data && !form) setForm(fromOrg(org.data)) }, [org.data, form])

  if (org.isError) return <LoadError error={org.error} what="your organization's settings" />
  if (!org.data || !form) return <p>Loading…</p>
  const o = org.data
  const canEdit = o.role === 'admin'
  const set = (k: keyof Form, v: string) => { setForm({ ...form, [k]: v }); setOk(false) }
  const preview = { name: form.brand_name || o.brand.name, logo_url: o.linked ? o.brand.logo_url : form.logo_url || null,
    primary_color: o.linked ? o.brand.primary_color : (/^#[0-9a-f]{6}$/i.test(form.primary_color) ? form.primary_color : null), accent_color: null }

  async function submit() {
    setProblems([])
    const body: OrgSettingsPatch = { brand_name: form!.brand_name, email_from_name: form!.email_from_name, reply_to_email: form!.reply_to_email, sms_from: form!.sms_from }
    if (!o.linked) body.brand = { logo_url: form!.logo_url, primary_color: form!.primary_color, accent_color: form!.accent_color }
    try {
      setForm(fromOrg(await save.mutateAsync(body)))
      setOk(true)
    } catch (e) {
      setProblems(e instanceof ApiError ? (e.problems.length ? e.problems : [e.message]) : ['That did not work.'])
    }
  }

  const field = (k: keyof Form, label: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}, help?: string) => (
    <label className="field-group"><span>{label}</span>
      <input value={form[k]} disabled={!canEdit} onChange={(e) => set(k, e.target.value)} {...extra} />
      {help && <span className="help">{help}</span>}
    </label>
  )

  return (
    <div className="stack narrow-form">
      <h1>Settings</h1>
      <p className="help">{o.name} · {o.account_type === 'reseller' ? 'reseller' : 'direct customer'}{o.linked ? ' · linked to Voicent-App' : ''}</p>
      {!canEdit && <Banner>Only an admin of {o.name} can change these.</Banner>}

      <section className="card stack" aria-labelledby="brand-h">
        <h2 id="brand-h">What your clients see</h2>
        {field('brand_name', 'Name shown to clients', { maxLength: 120, placeholder: o.brand.name }, `Leave blank to use “${o.brand.name}”.`)}
        {o.linked ? (
          <p className="help">Your logo and colours come from Voicent-App. Change them there (Settings → Branding); they show up here within a few minutes.</p>
        ) : (
          <>
            {field('logo_url', 'Logo address', { type: 'url', inputMode: 'url', placeholder: 'https://…/logo.png', maxLength: 500 })}
            <div className="grid-2">
              {field('primary_color', 'Main colour', { placeholder: '#0b5cff', maxLength: 7 })}
              {field('accent_color', 'Accent colour', { placeholder: '#0a6b35', maxLength: 7 })}
            </div>
          </>
        )}
        <div className="brand-sample" style={brandStyle(preview)} aria-label="How it looks">
          {safeLogo(preview.logo_url) ? <img src={safeLogo(preview.logo_url)!} alt="" className="portal-logo" referrerPolicy="no-referrer" /> : <strong>{preview.name}</strong>}
          <button type="button" className="btn btn-primary" tabIndex={-1}>Continue</button>
        </div>
      </section>

      <section className="card stack" aria-labelledby="senders-h">
        <h2 id="senders-h">How reminders reach your clients</h2>
        {field('email_from_name', 'Emails come from (name)', { maxLength: 120, placeholder: preview.name }, o.email_from_preview ? `Clients see: ${o.email_from_preview}` : undefined)}
        {field('reply_to_email', 'Replies go to', { type: 'email', inputMode: 'email', maxLength: 200, placeholder: 'help@yourcompany.com' })}
        {field('sms_from', 'Texts come from', { type: 'tel', inputMode: 'tel', maxLength: 20, placeholder: '+15551234567' },
          'A number on the Voicent text messaging account set aside for you. Leave blank to use the standard one.')}
      </section>

      {problems.length > 0 && <Problems problems={problems} />}
      {ok && <Banner kind="ok">Saved.</Banner>}
      {canEdit && <div className="row"><button type="button" className="btn btn-primary" disabled={save.isPending} onClick={() => void submit()}>{save.isPending ? 'Saving…' : 'Save settings'}</button></div>}
    </div>
  )
}
