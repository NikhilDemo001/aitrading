import { http } from './http'

export interface LlmStatus {
  enabled: boolean
  configured_on: boolean
  key_available: boolean
  model: string
  calls_today: number
  daily_cap: number
  budget_remaining: number
}

export interface DecisionEntry {
  time: string
  type: string // pick | skip | trade | ...
  symbol: string
  reason: string
  gate?: string
}

export interface LlmCall {
  time?: string
  timestamp?: string
  kind?: string
  model?: string
  source?: string
  prompt_tokens?: number
  completion_tokens?: number
  [key: string]: unknown
}

export interface Proposal {
  id?: string
  status?: string
  strategy?: string
  created_at?: string
  [key: string]: unknown
}

export const systemApi = {
  getLlmStatus: () => http.get<LlmStatus>('/api/llm-status'),
  getMyIp: () => http.get<{ ip: string; error?: string }>('/api/my-ip'),
  getDecisions: (limit = 200) => http.get<DecisionEntry[]>(`/api/decisions?limit=${limit}`),
  getLlmCalls: (limit = 100) => http.get<LlmCall[]>(`/api/llm-calls?limit=${limit}`),
  getProposals: () => http.get<Proposal[]>('/api/proposals'),
}
