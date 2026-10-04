import { createContext, useContext } from 'react'

export const InvestigationContext = createContext(null)

export function useInvestigation() {
  return useContext(InvestigationContext)
}
