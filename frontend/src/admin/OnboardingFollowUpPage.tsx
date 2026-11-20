import { useState } from 'react'
import { useParams } from 'react-router'
import { useClients, useOnboarding } from '../api/admin'
import type { LinkInfo } from '../api/types'
import AiosPanel from './AiosPanel'
import { LinksPanel } from './LinksPanel'
import RemindersPanel from './RemindersPanel'
import VoicentPanel from './VoicentPanel'

/** Everything about reaching the client and what happens after: links, reminders, the AIOS board and the Voicent workspace. */
export default function OnboardingFollowUpPage() {
  const { id = '' } = useParams()
  const ob = useOnboarding(id)
  const clients = useClients()
  const [issued, setIssued] = useState<LinkInfo[]>([])
  if (!ob.data) return null // the layout shows loading and errors
  const contacts = clients.data?.find((c) => c.id === ob.data.client_id)?.contacts ?? []
  return (
    <div className="stack">
      <LinksPanel id={id} contacts={contacts} issued={issued} onIssued={setIssued} />
      <RemindersPanel ob={ob.data} />
      <AiosPanel ob={ob.data} />
      <VoicentPanel ob={ob.data} />
    </div>
  )
}
