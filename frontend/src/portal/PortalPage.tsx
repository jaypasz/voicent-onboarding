import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useParams } from 'react-router'
import type { PortalView } from '../api/types'
import { Banner } from '../components/Banner'
import { ProgressBar } from '../components/ProgressBar'
import { StepTracker } from '../components/StepTracker'
import ChecklistLayout from './ChecklistLayout'
import FocusLayout from './FocusLayout'
import { PortalSessionProvider, usePortal } from './session'
import { BrandName } from './brand'
import { brandStyle, safeLogo } from '../lib/brand'

export default function PortalPage() {
  const { token = '' } = useParams()
  return (
    <PortalSessionProvider linkToken={token}>
      <PortalInner linkToken={token} />
    </PortalSessionProvider>
  )
}

function Message({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <main className="narrow stack center">
      <h1>{title}</h1>
      {children}
    </main>
  )
}

function PortalInner({ linkToken }: { linkToken: string }) {
  const { status, call } = usePortal()
  const q = useQuery({ queryKey: ['portal', linkToken], queryFn: () => call<PortalView>('/portal/onboarding'), enabled: status === 'ready', retry: false })

  useEffect(() => {
    document.title = q.data ? `${q.data.title}${q.data.brand?.name ? ` · ${q.data.brand.name}` : ''}` : 'Your onboarding'
  }, [q.data])

  if (status === 'unavailable') {
    return (
      <Message title="This link isn't available">
        <p>It may have expired or been replaced. Ask us for a new one and we'll send it over.</p>
      </Message>
    )
  }
  if (status === 'busy') return <Message title="Please try again in a minute"><p>There have been a lot of requests. Nothing is wrong with your link.</p></Message>
  if (status === 'error' || q.isError) {
    return (
      <Message title="Something went wrong">
        <p>We couldn't load your onboarding.</p>
        <button className="btn btn-primary" onClick={() => location.reload()}>Try again</button>
      </Message>
    )
  }
  if (status === 'loading' || q.isPending || !q.data) return <Message title="Loading your onboarding…" />

  return <PortalScreen view={q.data} onChanged={() => q.refetch()} />
}

/** What a client sees. The admin's client preview renders this same screen with a read-only session. */
export function PortalScreen({ view, onChanged, preview = false }: { view: PortalView; onChanged: () => Promise<unknown>; preview?: boolean }) {
  const logo = safeLogo(view.brand?.logo_url)
  return (
    <BrandName.Provider value={view.brand?.name || ''}>
      <main className={`portal portal-${view.layout}${preview ? ' is-preview' : ''}`} style={brandStyle(view.brand)}>
        <header className="portal-head">
          {(logo || view.brand?.name) && (
            <div className="portal-brand">
              {logo ? <img src={logo} alt={view.brand?.name || ''} className="portal-logo" referrerPolicy="no-referrer" /> : <strong>{view.brand?.name}</strong>}
            </div>
          )}
          <div className="eyebrow">{view.client_name}</div>
          <h1>{view.title}</h1>
          <ProgressBar progress={view.progress} label="Your progress" />
          <StepTracker steps={view.steps} label="Your steps" />
        </header>
        {view.status === 'paused' && <Banner kind="warn">This onboarding is paused. You can read everything, but changes are switched off until we resume it.</Banner>}
        {view.status === 'completed' && <Banner kind="ok">This onboarding is complete. Thank you!</Banner>}
        {view.layout === 'focus' ? <FocusLayout view={view} onChanged={onChanged} preview={preview} /> : <ChecklistLayout view={view} onChanged={onChanged} preview={preview} />}
      </main>
    </BrandName.Provider>
  )
}
