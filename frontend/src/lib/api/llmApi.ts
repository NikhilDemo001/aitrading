import { http } from './http'

export interface KindUsage {
  calls: number
  input_tokens: number
  output_tokens: number
  thinking_tokens: number
  ok: number
  failed: number
}

export interface Budget {
  used: number
  cap: number
  remaining: number
}

export interface LlmUsage {
  date: string
  model: string
  provider: string
  enabled: boolean
  calls_total: number
  /** Today's calls logged before token capture existed — they can't be counted. */
  calls_missing_tokens: number
  input_tokens: number
  output_tokens: number
  thinking_tokens: number
  total_tokens: number
  by_kind: Record<string, KindUsage>
  cost: {
    priced: boolean
    usd: number | null
    inr: number | null
    input_rate_per_mtok_usd: number
    output_rate_per_mtok_usd: number
    usd_inr_rate: number
  }
  budgets: { trading: Budget; assistant: Budget }
}

export const llmApi = {
  getUsage: () => http.get<LlmUsage>('/api/llm-usage'),
}
