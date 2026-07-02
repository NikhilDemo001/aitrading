import { http } from './http'

export interface LeaderboardEntry {
  rank: number
  name: string
  id: string
  profit_factor: number
  drawdown: number
  consistency: number
  sharpe_ratio: number
  expectancy: number
  status: string
}

export interface StrategySummary {
  id: string
  name: string
  status: string
  current_score: number
  version: number
  created_at: string
}

export interface ResearchSummary {
  total_strategies: number
  under_research: number
  backtesting: number
  walkforward: number
  validation: number
  papertrading: number
  live_candidates: number
  approved: number
  retired: number
  rejected: number
}

export interface StrategyDetail {
  id: string
  name: string
  created_at: string
  status: string
  current_score: number
  active_version?: {
    version: number
    entry_rules: string
    exit_rules: string
    stop_loss_rules: string
    target_rules: string
    sizing_rules: string
    parameters: Array<{ indicator_name: string; parameter_key: string; parameter_value: string }>
    hypothesis?: { pattern_description: string; evidence: string; reasoning: string; assumed_regimes: string; risks: string }
    backtest?: { total_trades: number; win_rate: number; profit_factor: number; sharpe_ratio: number; max_drawdown: number; expectancy: number }
    validation?: { score: number; stability_score: number; passed: number }
    paper_trade?: unknown
    improvements: unknown[]
  }
}

export interface ResearchStatus {
  status: string
  active_task: string
  progress: number
  last_activity: string
  last_active_time: string
}

export interface AllocationRow {
  strategy_id: string
  name: string
  percentage: number
  regime_match: boolean
  regime_notes: string
}

export interface Hypothesis {
  id: number
  name: string
  strat_id: string
  pattern_description: string
  evidence: string
  reasoning: string
  status: string
  current_score: number
}

export interface TimelineEvent {
  type: string
  strategy_id: string
  title: string
  observation?: string
  improvement?: string
  result?: string
  created_at: string
}

export interface JournalEntry {
  id: number
  created_at: string
  findings: string
  mistakes: string
  opportunities: string
  weaknesses: string
  strengths: string
}

export interface Briefing {
  best_strategy_name: string
  best_strategy_id: string
  best_strategy_pf: number
  retire_strategy_name: string
  retire_strategy_pf: number
  improving_strategy_name: string
  improving_strategy_version: number
  voice_of_ai: string
  market_summary: string
  new_discoveries: number
  paper_pnl: number
  paper_win_rate: number
  paper_trades: number
  risk_alerts: string[]
}

export const researchApi = {
  getSummary: () => http.get<ResearchSummary>('/api/research/summary'),
  getStrategies: () => http.get<StrategySummary[]>('/api/research/strategies'),
  getStrategy: (id: string) => http.get<StrategyDetail>(`/api/research/strategy/${id}`),
  getLeaderboard: () => http.get<LeaderboardEntry[]>('/api/research/leaderboard'),
  getStatus: () => http.get<ResearchStatus>('/api/research/status'),
  getAllocation: () => http.get<AllocationRow[]>('/api/research/allocation'),
  getHypotheses: () => http.get<Hypothesis[]>('/api/research/hypotheses'),
  getTimeline: (date?: string) => http.get<TimelineEvent[]>(`/api/research/timeline${date ? `?date=${date}` : ''}`),
  getJournal: (date?: string) => http.get<JournalEntry[]>(`/api/research/journal${date ? `?date=${date}` : ''}`),
  getBriefing: () => http.get<Briefing>('/api/research/briefing'),

  discover: (count = 5) => http.post(`/api/research/discover?count=${count}`),
  backtest: (strategyId: string, version = 1) => http.post(`/api/research/backtest?strategy_id=${strategyId}&version=${version}`),
  validate: (strategyId: string, version = 1) => http.post(`/api/research/validate?strategy_id=${strategyId}&version=${version}`),
  evolve: (strategyId: string) => http.post(`/api/research/evolve?strategy_id=${strategyId}`),
  battle: (tournamentName: string, strategyIds: string[]) =>
    http.post('/api/research/battle', { tournament_name: tournamentName, strategy_ids: strategyIds }),
  control: (strategyId: string, status: string) => http.post('/api/research/control', { strategy_id: strategyId, status }),
  chat: (query: string) => http.post<{ title: string; text: string }>('/api/research/chat', { query }),
}
