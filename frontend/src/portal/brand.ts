import { createContext, useContext } from 'react'

/** The name of the business behind this portal: the org's brand name (a reseller, never Voicent, for a reseller's clients). */
export const BrandName = createContext('')

/** What a client sees as the author of a comment from the team. */
export function useTeamName(): string {
  return useContext(BrandName) || 'Your onboarding team'
}
