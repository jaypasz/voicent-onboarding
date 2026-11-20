import type { TeamMember } from '../api/types'

export const memberLabel = (m?: Pick<TeamMember, 'name' | 'email'> | null): string => (m ? m.name || m.email || 'Someone' : 'Nobody')

export const ROLE_LABEL: Record<string, string> = {
  admin: 'Admin', manager: 'Manager', member: 'Member', viewer: 'Viewer (can look, not change)',
}
