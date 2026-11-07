import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useParams } from 'react-router'
import type { PortalView } from '../api/types'
import { Banner } from '../components/Banner'
import { ProgressBar } from '../components/ProgressBar'
import ChecklistLayout from './ChecklistLayout'
import FocusLayout from './FocusLayout'
import { PortalSessionProvider, usePortal } from './session'

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
    document.title = q.data ? `${q.data.title}` : 'Your onboarding'
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

  const view = q.data
  const onChanged = () => q.refetch()
  return (
    <main className={`portal portal-${view.layout}`}>
      <header className="portal-head">
        <div className="eyebrow">{view.client_name}</div>
        <h1>{view.title}</h1>
        <ProgressBar progress={view.progress} label="Your progress" />
      </header>
      {view.status === 'paused' && <Banner kind="warn">This onboarding is paused. You can read everything, but changes are switched off until we resume it.</Banner>}
      {view.status === 'completed' && <Banner kind="ok">This onboarding is complete. Thank you!</Banner>}
      {view.layout === 'focus' ? <FocusLayout view={view} onChanged={onChanged} /> : <ChecklistLayout view={view} onChanged={onChanged} />}
    </main>
  )
}
