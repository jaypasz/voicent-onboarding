import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './http'
import type {
  Client, Contact, Features, LinkInfo, NudgeResult, NudgeRow, OnboardingDetail, OnboardingStatus, OnboardingSummary, SentOnboarding, SyncState, TemplateDetail,
  TemplateSummary, YamlImportResult,
} from './types'

const k = {
  clients: ['clients'] as const,
  templates: ['templates'] as const,
  onboardings: ['onboardings'] as const,
  onboarding: (id: string) => ['onboarding', id] as const,
  links: (id: string) => ['links', id] as const,
}

// ------------------------------------------------------------------ reads

export const useClients = () => useQuery({ queryKey: k.clients, queryFn: () => request<Client[]>('/clients') })
export const useTemplates = () => useQuery({ queryKey: k.templates, queryFn: () => request<TemplateSummary[]>('/templates') })
export const useTemplate = (id: string) => useQuery({ queryKey: ['template', id], queryFn: () => request<TemplateDetail>(`/templates/${id}`) })
export const useOnboardings = (status?: OnboardingStatus | '') =>
  useQuery({ queryKey: [...k.onboardings, status ?? ''], queryFn: () => request<OnboardingSummary[]>(`/onboardings${status ? `?status=${status}` : ''}`) })
export const useOnboarding = (id: string) => useQuery({ queryKey: k.onboarding(id), queryFn: () => request<OnboardingDetail>(`/onboardings/${id}`) })
export const useFeatures = () => useQuery({ queryKey: ['features'], queryFn: () => request<Features>('/features'), staleTime: 60_000 })
export const useNudgeHistory = (id: string) => useQuery({ queryKey: ['nudges', id], queryFn: () => request<NudgeRow[]>(`/onboardings/${id}/nudges`) })
export const useSyncStatus = (id: string) => useQuery({ queryKey: ['sync', id], queryFn: () => request<SyncState>(`/onboardings/${id}/sync`) })
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
  useWrite((b: { client_id: string; template_id: string; title?: string }) => request<OnboardingDetail>('/onboardings', { body: b }), () => [k.onboardings])

type Action = 'pause' | 'resume' | 'archive'
export const useOnboardingAction = (id: string) =>
  useWrite((a: Action) => request<OnboardingDetail>(`/onboardings/${id}/${a}`, { body: {} }), () => [k.onboarding(id), k.onboardings])
export const useSend = (id: string) => useWrite(() => request<SentOnboarding>(`/onboardings/${id}/send`, { body: {} }), () => [k.onboarding(id), k.onboardings, k.links(id)])

type StepAction = 'complete' | 'skip' | 'reopen'
export const useStepAction = (id: string) =>
  useWrite((a: { key: string; action: StepAction }) => request(`/onboardings/${id}/steps/${a.key}/${a.action}`, { body: {} }), () => [k.onboarding(id), k.onboardings])
export const useAnswerStep = (id: string) =>
  useWrite((a: { key: string; data: unknown }) => request(`/onboardings/${id}/steps/${a.key}`, { method: 'PUT', body: { data: a.data } }), () => [k.onboarding(id), k.onboardings])
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
