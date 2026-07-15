import { http } from './http'

export interface RatioRow { name: string; company_value: string; sector_value: string }
export interface HistPoint { period: string; value: number; change?: string }
export interface CategoryHistory { category: string; history: HistPoint[] }

export interface Profile {
  company_profile: string
  sector: string
  sector_market_cap_inr?: { formatted: string }
  sector_market_cap_usd?: { formatted: string }
}

export interface BalanceRow { total_asset: number; total_liability: number; period: string }

export interface CorpAction {
  name: string
  expiry_date: string
  amount: number | null
  ratio: string | null
  event_details: { name: string; value: string }[]
}

export interface Competitor {
  instrument_key: string
  company_profile: string
  sector: string
  sector_market_cap_inr?: { formatted: string }
}

export interface Fundamentals {
  symbol: string
  isin: string
  profile: Profile | null
  key_ratios: RatioRow[] | null
  income_statement: { income_statement: CategoryHistory[] } | null
  balance_sheet: { history: BalanceRow[] } | null
  cash_flow: { cash_flow: CategoryHistory[] } | null
  share_holdings: CategoryHistory[] | null
  corporate_actions: CorpAction[] | null
  competitors: Competitor[] | null
}

export const fundamentalsApi = {
  get: (symbol: string) => http.get<Fundamentals>(`/api/fundamentals/${encodeURIComponent(symbol)}`),
}
