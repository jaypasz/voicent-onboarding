import { useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { usePreview } from '../api/admin'
import { ApiError } from '../api/http'
import { LoadError } from '../components/LoadError'
import { PortalScreen } from '../portal/PortalPage'
import { PortalContext, type PortalApi } from '../portal/session'

/** Read-only: any attempt to change something says so, and the server marks every step as not writable anyway. */
const readOnly: PortalApi = {
  status: 'ready',
  call: async () => { throw new ApiError(403, "This is a preview. Nothing here can be changed.") },
}

/** The onboarding exactly as a client sees it, with their brand, for one of the client's contacts. Works for a draft too. */
export default function OnboardingPreviewPage() {
  const { id = '' } = useParams()
  const [contactId, setContactId] = useState('')
  const view = usePreview(id, contactId)
  const api = useMemo(() => readOnly, [])
  if (view.isError) return <LoadError error={view.error} what="the client preview" />
  if (!view.data) return <p>Loading the preview…</p>
  const v = view.data
  return (
    <div className="stack">
      <div className="row wrap between">
        <p className="help">What {v.contacts.length ? (v.contacts.find((c) => c.id === v.contact.id)?.name ?? v.contact.name) : 'anyone with a link'} sees. Nothing here can be changed.</p>
        {v.contacts.length > 1 && (
          <label className="field-group"><span>See it as</span>
            <select value={contactId || v.contact.id} onChange={(e) => setContactId(e.target.value)}>
              {v.contacts.map((c) => <option key={c.id} value={c.id}>{c.name}{c.role ? ` (${c.role})` : ''}</option>)}
            </select>
          </label>
        )}
      </div>
      {v.status === 'draft' && <p className="help">This is still a draft: the client can't open it until you send it.</p>}
      <div className="preview-frame" aria-label="Client preview" role="region">
        <PortalContext.Provider value={api}>
          <PortalScreen view={v} onChanged={() => view.refetch()} preview />
        </PortalContext.Provider>
      </div>
    </div>
  )
}
