import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './http'
import type {
  AppNotification, Client, Contact, Features, Me, Team, OnboardingDocument, OrgSettings, PreviewView, TemplateCheck, LinkInfo, NudgeResult, NudgeRow, OnboardingDetail, OnboardingStatus, OnboardingSummary, ProvisionStatus, SentOnboarding, SyncState, TemplateDetail,
  TemplateSummary, YamlImportResult, Task, TeamStepTask,
} from './types'
import type { SectionDoc, StepDoc, TemplateDoc } from '../builder/doc'

const k = {
  clients: ['clients'] as const,
  templates: ['templates'] as const,
  onboardings: ['onboardings'] as const,
  onboarding: (id: string) => ['onboarding', id] as const,
  links: (id: string) => ['links', id] as const,
}

// ------------------------------------------------------------------ reads

export const useClients = () => useQuery({ queryKey: k.clients, queryFn: () => request<Client[]>('/clients') })
export const useTemplates = (includeArchived = false) => useQuery({
  queryKey: includeArchived ? [...k.templates, 'with-archived'] : k.templates,
  queryFn: () => request<TemplateSummary[]>(includeArchived ? '/templates?include_archived=true' : '/templates'),
})
export const useTemplate = (id: string) => useQuery({ queryKey: ['template', id], queryFn: () => request<TemplateDetail>(`/templates/${id}`), enabled: !!id })
export const useOnboardings = (status?: OnboardingStatus | '', mine = false) => {
  const q = new URLSearchParams()
  if (status) q.set('status', status)
  if (mine) q.set('mine', '1')
  const qs = q.toString()
  return useQuery({ queryKey: [...k.onboardings, status ?? '', mine], queryFn: () => request<OnboardingSummary[]>(`/onboardings${qs ? `?${qs}` : ''}`) })
}
export const useOnboarding = (id: string) => useQuery({ queryKey: k.onboarding(id), queryFn: () => request<OnboardingDetail>(`/onboardings/${id}`) })
export const useFeatures = () => useQuery({ queryKey: ['features'], queryFn: () => request<Features>('/features'), staleTime: 60_000 })
export const useNudgeHistory = (id: string) => useQuery({ queryKey: ['nudges', id], queryFn: () => request<NudgeRow[]>(`/onboardings/${id}/nudges`) })
export const useSyncStatus = (id: string) => useQuery({ queryKey: ['sync', id], queryFn: () => request<SyncState>(`/onboardings/${id}/sync`) })
/** While a delivery is waiting or under way it is read again every few seconds, so its outcome shows without a reload. */
export const PROVISION_POLL_MS = 5_000
export const useProvisionStatus = (id: string) => useQuery({
  queryKey: ['provision', id],
  queryFn: () => request<ProvisionStatus>(`/onboardings/${id}/provision`),
  refetchInterval: (q) => (q.state.data?.state === 'pending' ? PROVISION_POLL_MS : false),
})
export const useOnboardingDocument = (id: string) =>
  useQuery({ queryKey: ['document', id], queryFn: () => request<OnboardingDocument>(`/onboardings/${id}/document`) })
export const useMe = () => useQuery({ queryKey: ['me'], queryFn: () => request<Me>('/me'), staleTime: 60_000 })
export const useOrgSettings = (enabled = true) => useQuery({ queryKey: ['org'], queryFn: () => request<OrgSettings>('/org'), staleTime: 60_000, enabled })
export const usePreview = (id: string, contactId: string) =>
  useQuery({ queryKey: ['preview', id, contactId], queryFn: () => request<PreviewView>(`/onboardings/${id}/preview${contactId ? `?contact_id=${encodeURIComponent(contactId)}` : ''}`) })
export const useLinks = (id: string) => useQuery({ queryKey: k.links(id), queryFn: () => request<LinkInfo[]>(`/onboardings/${id}/links`) })

// ------------------------------------------------------------------ writes

function useWrite<A, R>(fn: (a: A) => Promise<R>, invalidate: (a: A, r: R) => (readonly unknown[])[]) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (r, a) => {
      for (const key of invalidate(a, r)) void qc.invalidateQueries({ queryKey: key })
    },
  })
}

export const useCreateClient = () =>
  useWrite((b: { name: string; kind: Client['kind']; notes?: string }) => request<Client>('/clients', { body: b }), () => [k.clients])
export const useUpdateClient = (id: string) =>
  useWrite((b: Partial<Pick<Client, 'name' | 'kind' | 'status' | 'notes' | 'timezone'>>) => request<Client>(`/clients/${id}`, { method: 'PATCH', body: b }), () => [k.clients])
export const useAddContact = (clientId: string) =>
  useWrite((b: Partial<Contact> & { name: string }) => request<Contact>(`/clients/${clientId}/contacts`, { body: b }), () => [k.clients])
export const useUpdateContact = (clientId: string) =>
  useWrite((a: { id: string; patch: Partial<Contact> }) => request<Contact>(`/clients/${clientId}/contacts/${a.id}`, { method: 'PATCH', body: a.patch }), () => [k.clients])

export const useInstallPresets = () => useWrite(() => request<{ added: string[] }>('/templates/install-presets', { method: 'POST', body: {} }), () => [k.templates])
export const useImportYaml = () =>
  useWrite((a: { yaml: string; dry_run: boolean }) => request<YamlImportResult>('/templates/import', { body: a }), (a) => (a.dry_run ? [] : [k.templates]))
export const fetchTemplateYaml = (id: string) => request<string>(`/templates/${id}/export`, { text: true })

export const useCreateOnboarding = () =>
  useWrite((b: { client_id: string; template_id: string; title?: string; sections?: SectionDoc[]; steps?: StepDoc[] }) => request<OnboardingDetail>('/onboardings', { body: b }), () => [k.onboardings])
export const useSaveOnboardingSteps = (id: string) =>
  useWrite((b: { sections: SectionDoc[]; steps: StepDoc[]; etag?: string; notify_client?: boolean }) => request<OnboardingDetail & OnboardingDocument>(`/onboardings/${id}/document`, { method: 'PUT', body: b }),
    () => [k.onboarding(id), k.onboardings, ['document', id]])

export const useSaveTemplate = () =>
  useWrite((doc: TemplateDoc) => request<TemplateDetail>('/templates', { body: doc }), (_a, r) => [k.templates, ['template', r.id]])
/** Only ever a new template: the server refuses a name already in use, archived templates included. */
export const useCreateTemplate = () =>
  useWrite((doc: TemplateDoc) => request<TemplateDetail>('/templates?new=true', { body: doc }), (_a, r) => [k.templates, ['template', r.id]])
export const checkTemplate = (doc: TemplateDoc) => request<TemplateCheck>('/templates/validate', { body: doc })

type Action = 'pause' | 'resume' | 'archive'
export const useOnboardingAction = (id: string) =>
  useWrite((a: Action) => request<OnboardingDetail>(`/onboardings/${id}/${a}`, { body: {} }), () => [k.onboarding(id), k.onboardings])
export const useSend = (id: string) => useWrite(() => request<SentOnboarding>(`/onboardings/${id}/send`, { body: {} }), () => [k.onboarding(id), k.onboardings, k.links(id)])

type StepAction = 'complete' | 'skip' | 'reopen'
export const useStepAction = (id: string) =>
  useWrite((a: { key: string; action: StepAction }) => request(`/onboardings/${id}/steps/${a.key}/${a.action}`, { body: {} }), () => [k.onboarding(id), k.onboardings, ['provision', id]])
export const useAnswerStep = (id: string) =>
  useWrite((a: { key: string; data: unknown }) => request(`/onboardings/${id}/steps/${a.key}`, { method: 'PUT', body: { data: a.data } }), () => [k.onboarding(id), k.onboardings, ['provision', id]])
export const useAdminComment = (id: string) =>
  useWrite((a: { key: string; body: string; client_visible: boolean }) => request(`/onboardings/${id}/steps/${a.key}/comments`, { body: { body: a.body, client_visible: a.client_visible } }), () => [k.onboarding(id)])

export const useIssueLink = (id: string) =>
  useWrite((contact_id: string) => request<LinkInfo>(`/onboardings/${id}/links`, { body: { contact_id } }), () => [k.links(id)])
export const useRevokeLink = (id: string) => useWrite((linkId: string) => request<LinkInfo>(`/onboardings/${id}/links/${linkId}/revoke`, { body: {} }), () => [k.links(id)])
export const useExtendLink = (id: string) =>
  useWrite((a: { linkId: string; days: number }) => request<LinkInfo>(`/onboardings/${id}/links/${a.linkId}/extend`, { body: { days: a.days } }), () => [k.links(id)])
export const fetchFileUrl = (onboardingId: string, fileId: string) => request<{ name: string; url: string }>(`/onboardings/${onboardingId}/files/${fileId}/url`)

export const useRemindNow = (id: string) =>
  useWrite(() => request<{ results: NudgeResult[]; message: string }>(`/onboardings/${id}/nudge`, { body: {} }), () => [['nudges', id], k.onboarding(id)])
export const usePauseReminders = (id: string) =>
  useWrite((paused: boolean) => request<OnboardingSummary>(`/onboardings/${id}/nudges`, { method: 'PUT', body: { paused } }), () => [k.onboarding(id), k.onboardings])
export const useSyncNow = (id: string) => useWrite(() => request<SyncState>(`/onboardings/${id}/sync`, { body: {} }), () => [['sync', id]])
export const useProvisionNow = (id: string) =>
  useWrite(() => request<ProvisionStatus>(`/onboardings/${id}/provision`, { body: {} }), () => [['provision', id], k.onboardings])

export type OrgSettingsPatch = Partial<Pick<OrgSettings, 'brand_name' | 'email_from_name' | 'reply_to_email' | 'sms_from'>> & {
  brand?: { logo_url: string; primary_color: string; accent_color: string }
}
export const useSaveOrgSettings = () => useWrite((b: OrgSettingsPatch) => request<OrgSettings>('/org', { method: 'PUT', body: b }), () => [['org']])
export const useSetPaying = (clientId: string) =>
  useWrite((paying: boolean) => request<Client>(`/clients/${clientId}/paying`, { body: { paying } }), () => [k.clients, ['provision'], k.onboardings])

export const useSetOutcome = (clientId: string) =>
  useWrite((outcome: 'lost' | 'stalled' | null) => request<Client>(`/clients/${clientId}/outcome`, { body: { outcome } }), () => [k.clients])

export type TaskFilter = { clientId?: string; assigneeId?: string; done?: boolean }
export const useTasks = (f: TaskFilter = {}) => {
  const q = new URLSearchParams()
  if (f.clientId) q.set('client_id', f.clientId)
  if (f.assigneeId) q.set('assignee_id', f.assigneeId)
  if (f.done !== undefined) q.set('done', String(f.done))
  const qs = q.toString()
  return useQuery({ queryKey: ['tasks', qs], queryFn: () => request<Task[]>(`/tasks${qs ? `?${qs}` : ''}`) })
}
export const useCreateTask = () =>
  useWrite((b: { client_id: string; title: string; assignee_id?: string | null; due_on?: string | null }) => request<Task>('/tasks', { body: b }), () => [['tasks']])
export const useUpdateTask = () =>
  useWrite((a: { id: string; patch: { title?: string; assignee_id?: string | null; due_on?: string | null; done?: boolean } }) => request<Task>(`/tasks/${a.id}`, { method: 'PATCH', body: a.patch }), () => [['tasks']])
/** Team tasks that sit in an onboarding's flow, to list beside the standalone ones. */
export const useTeamStepTasks = (f: { assigneeId?: string; done?: boolean } = {}) => {
  const q = new URLSearchParams()
  if (f.assigneeId) q.set('assignee_id', f.assigneeId)
  if (f.done !== undefined) q.set('done', String(f.done))
  const qs = q.toString()
  return useQuery({ queryKey: ['tasks', 'in-onboardings', qs], queryFn: () => request<TeamStepTask[]>(`/tasks/in-onboardings${qs ? `?${qs}` : ''}`) })
}
export const useDeleteTask = () => useWrite((id: string) => request(`/tasks/${id}`, { method: 'DELETE' }), () => [['tasks']])

export const useTeam = () => useQuery({ queryKey: ['team'], queryFn: () => request<Team>('/team'), staleTime: 60_000 })
export const useInvite = () => useWrite((b: { email: string; role: string }) => request('/team/invites', { body: b }), () => [['team']])
export const useCancelInvite = () => useWrite((id: string) => request(`/team/invites/${id}`, { method: 'DELETE' }), () => [['team']])
export const useChangeMember = () => useWrite((a: { id: string; role: string }) => request(`/team/members/${a.id}`, { method: 'PATCH', body: { role: a.role } }), () => [['team']])
export const useRemoveMember = () => useWrite((id: string) => request(`/team/members/${id}`, { method: 'DELETE' }), () => [['team']])
export const useUpdateMe = () => useWrite((b: { notify_email?: boolean; name?: string }) => request('/team/me', { method: 'PUT', body: b }), () => [['team']])

export const useNotifications = () =>
  useQuery({ queryKey: ['notifications'], queryFn: () => request<{ unread: number; items: AppNotification[] }>('/notifications'), refetchInterval: 60_000 })
export const useMarkRead = () => useWrite((ids?: string[]) => request('/notifications/read', { body: ids ? { ids } : {} }), () => [['notifications']])

export const useSetOwner = (id: string) =>
  useWrite((member_id: string | null) => request<OnboardingDetail>(`/onboardings/${id}/owner`, { method: 'PUT', body: { member_id } }), () => [k.onboarding(id), k.onboardings])
export const useSetStepFollower = (id: string) =>
  useWrite((a: { key: string; member_id: string | null }) => request(`/onboardings/${id}/steps/${a.key}/team-assignee`, { method: 'PUT', body: { member_id: a.member_id } }), () => [k.onboarding(id)])
