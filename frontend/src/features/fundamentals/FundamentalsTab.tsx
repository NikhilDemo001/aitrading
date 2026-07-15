import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useBotStore, EMPTY_WATCHLIST } from '../../lib/stores/useBotStore'
import {
  fundamentalsApi,
  type CategoryHistory,
  type HistPoint,
  type RatioRow,
  type BalanceRow,
} from '../../lib/api/fundamentalsApi'
import './FundamentalsTab.css'

function fmtCr(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  if (abs >= 100000) return `${sign}₹${(abs / 100000).toFixed(2)} L Cr`
  return `${sign}₹${Math.round(abs).toLocaleString('en-IN')} Cr`
}

const tone = (change?: string) => (!change ? '' : change.trim().startsWith('-') ? 'neg' : 'pos')
const shortPeriod = (p: string) => p.replace(/^\w+ /, '') // "Mar 2025" -> "2025"

// Chronological mini bar-trend (input is newest-first).
function BarTrend({ history }: { history: HistPoint[] }) {
  const pts = [...history].reverse()
  const max = Math.max(...pts.map((p) => Math.abs(p.value)), 1)
  return (
    <div className="mq-fx-bars">
      {pts.map((p, i) => (
        <div key={i} className="mq-fx-barwrap" title={`${p.period}: ${fmtCr(p.value)}`}>
          <div className={`mq-fx-bar ${p.value < 0 ? 'neg' : ''}`}
               style={{ height: `${Math.max(6, (Math.abs(p.value) / max) * 100)}%` }} />
          <span className="mq-fx-barlbl">{shortPeriod(p.period)}</span>
        </div>
      ))}
    </div>
  )
}

function FinancialCard({ label, cat }: { label: string; cat?: CategoryHistory }) {
  if (!cat || !cat.history?.length) return null
  const latest = cat.history[0]
  return (
    <div className="mq-fx-fincard">
      <div className="mq-fx-fincard-top">
        <span className="mq-fx-fincard-label">{label}</span>
        {latest.change && <span className={`mq-fx-chip ${tone(latest.change)}`}>{latest.change}</span>}
      </div>
      <div className="mq-fx-fincard-val">{fmtCr(latest.value)}</div>
      <div className="mq-fx-fincard-period">{latest.period}</div>
      <BarTrend history={cat.history} />
    </div>
  )
}

const SH_COLORS: Record<string, string> = {
  promoters: '#38bdf8', fii: '#a78bfa', other_dii: '#34d399',
  mutual_funds: '#fbbf24', retail_and_other: '#94a3b8',
}
const SH_LABEL: Record<string, string> = {
  promoters: 'Promoters', fii: 'FII', other_dii: 'DII',
  mutual_funds: 'Mutual Funds', retail_and_other: 'Public / Other',
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="mq-fx-section">
      <div className="mq-fx-section-head">
        <h3>{title}</h3>{hint && <span className="mq-fx-hint">{hint}</span>}
      </div>
      {children}
    </section>
  )
}

export function FundamentalsTab() {
  const watchlist = useBotStore((s) => s.status?.watchlist ?? EMPTY_WATCHLIST)
  const [symbol, setSymbol] = useState<string | null>(null)
  const active = symbol ?? watchlist[0] ?? null

  const { data, isLoading, isError } = useQuery({
    queryKey: ['fundamentals', active],
    queryFn: () => fundamentalsApi.get(active as string),
    enabled: !!active,
    staleTime: 3_600_000, // fundamentals change quarterly; cache an hour
    retry: 0,
  })

  const profile = data?.profile
  const ratios = data?.key_ratios ?? []
  const income = data?.income_statement?.income_statement ?? []
  const cash = data?.cash_flow?.cash_flow ?? []
  const balance: BalanceRow[] = data?.balance_sheet?.history ?? []
  const holdings = data?.share_holdings ?? []
  const actions = data?.corporate_actions ?? []
  const competitors = data?.competitors ?? []

  const findCat = (arr: CategoryHistory[], c: string) => arr.find((x) => x.category === c)

  return (
    <div className="mq-fx">
      <div className="mq-fx-head">
        <div>
          <h2 className="mq-fx-title">{active ?? '—'} <span className="mq-fx-sub">Fundamentals</span></h2>
          {profile?.sector && <span className="mq-fx-sector">{profile.sector}</span>}
        </div>
        <label className="mq-fx-picker">
          <span>Symbol</span>
          <select value={active ?? ''} onChange={(e) => setSymbol(e.target.value)}>
            {watchlist.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>

      {!active ? (
        <div className="mq-fx-empty">No symbol selected.</div>
      ) : isLoading ? (
        <div className="mq-fx-empty">Loading fundamentals for {active}…</div>
      ) : isError ? (
        <div className="mq-fx-empty">Couldn't load fundamentals — check the Upstox session.</div>
      ) : !data ? (
        <div className="mq-fx-empty">No fundamentals available.</div>
      ) : (
        <>
          {/* Profile + sector cap */}
          {profile && (
            <Section title="Company Profile">
              <p className="mq-fx-desc">{profile.company_profile}</p>
              <div className="mq-fx-capstrip">
                {profile.sector_market_cap_inr?.formatted && (
                  <div className="mq-fx-cap"><span>Sector Mkt Cap</span><b>{profile.sector_market_cap_inr.formatted}</b></div>
                )}
                {profile.sector_market_cap_usd?.formatted && (
                  <div className="mq-fx-cap"><span>In USD</span><b>{profile.sector_market_cap_usd.formatted}</b></div>
                )}
              </div>
            </Section>
          )}

          {/* Key ratios vs sector */}
          {ratios.length > 0 && (
            <Section title="Key Ratios" hint="company vs sector benchmark">
              <div className="mq-fx-ratios">
                {ratios.map((r: RatioRow) => {
                  const cv = parseFloat(r.company_value) || 0
                  const sv = parseFloat(r.sector_value) || 0
                  const max = Math.max(cv, sv, 0.0001)
                  return (
                    <div key={r.name} className="mq-fx-ratio">
                      <div className="mq-fx-ratio-name">{r.name}</div>
                      <div className="mq-fx-ratio-val">{r.company_value}</div>
                      <div className="mq-fx-ratio-track">
                        <div className="mq-fx-ratio-fill co" style={{ width: `${(cv / max) * 100}%` }} />
                      </div>
                      <div className="mq-fx-ratio-track sector">
                        <div className="mq-fx-ratio-fill se" style={{ width: `${(sv / max) * 100}%` }} />
                      </div>
                      <div className="mq-fx-ratio-sector">sector {r.sector_value}</div>
                    </div>
                  )
                })}
              </div>
            </Section>
          )}

          {/* Financials */}
          {income.length > 0 && (
            <Section title="Income Statement" hint="latest period, YoY change, trend">
              <div className="mq-fx-fingrid">
                <FinancialCard label="Revenue" cat={findCat(income, 'revenue')} />
                <FinancialCard label="Operating Profit" cat={findCat(income, 'operating_profit')} />
                <FinancialCard label="Net Profit" cat={findCat(income, 'net_profit')} />
              </div>
            </Section>
          )}

          {cash.length > 0 && (
            <Section title="Cash Flow">
              <div className="mq-fx-fingrid">
                <FinancialCard label="Operating" cat={findCat(cash, 'operating')} />
                <FinancialCard label="Investing" cat={findCat(cash, 'investing')} />
                <FinancialCard label="Financing" cat={findCat(cash, 'financing')} />
              </div>
            </Section>
          )}

          {/* Balance sheet: assets vs liabilities */}
          {balance.length > 0 && (
            <Section title="Balance Sheet" hint="assets vs liabilities">
              <div className="mq-fx-bsheet">
                {[...balance].reverse().map((b, i) => {
                  const max = Math.max(...balance.map((x) => x.total_asset), 1)
                  return (
                    <div key={i} className="mq-fx-bs-col">
                      <div className="mq-fx-bs-bars">
                        <div className="mq-fx-bs-bar asset" style={{ height: `${(b.total_asset / max) * 100}%` }}
                             title={`Assets ${fmtCr(b.total_asset)}`} />
                        <div className="mq-fx-bs-bar liab" style={{ height: `${(b.total_liability / max) * 100}%` }}
                             title={`Liabilities ${fmtCr(b.total_liability)}`} />
                      </div>
                      <span className="mq-fx-bs-lbl">{shortPeriod(b.period)}</span>
                    </div>
                  )
                })}
                <div className="mq-fx-bs-legend">
                  <span><i className="asset" /> Assets</span>
                  <span><i className="liab" /> Liabilities</span>
                </div>
              </div>
            </Section>
          )}

          {/* Shareholding stacked bar */}
          {holdings.length > 0 && (
            <Section title="Shareholding" hint={holdings[0]?.history?.[0]?.period}>
              <div className="mq-fx-shbar">
                {holdings.map((h) => {
                  const pct = h.history?.[0]?.value ?? 0
                  return (
                    <div key={h.category} className="mq-fx-shseg"
                         style={{ width: `${pct}%`, background: SH_COLORS[h.category] ?? '#64748b' }}
                         title={`${SH_LABEL[h.category] ?? h.category}: ${pct}%`} />
                  )
                })}
              </div>
              <div className="mq-fx-shlegend">
                {holdings.map((h) => (
                  <span key={h.category}>
                    <i style={{ background: SH_COLORS[h.category] ?? '#64748b' }} />
                    {SH_LABEL[h.category] ?? h.category} <b>{h.history?.[0]?.value ?? 0}%</b>
                  </span>
                ))}
              </div>
            </Section>
          )}

          {/* Corporate actions */}
          {actions.length > 0 && (
            <Section title="Corporate Actions">
              <div className="mq-fx-actions">
                {actions.map((a, i) => (
                  <div key={i} className="mq-fx-action">
                    <div className="mq-fx-action-top">
                      <span className="mq-fx-action-name">{a.name}</span>
                      {a.amount != null && <span className="mq-fx-action-amt">₹{a.amount}</span>}
                      {a.ratio && <span className="mq-fx-action-amt">{a.ratio}</span>}
                    </div>
                    <div className="mq-fx-action-date">Ex/Record: {a.expiry_date}</div>
                    {a.event_details?.find((e) => e.name === 'Details') && (
                      <div className="mq-fx-action-det">{a.event_details.find((e) => e.name === 'Details')!.value}</div>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Competitors */}
          <Section title="Competitors">
            {competitors.length === 0 ? (
              <div className="mq-fx-none">No competitor data available.</div>
            ) : (
              <div className="mq-fx-comps">
                {competitors.map((c, i) => (
                  <div key={i} className="mq-fx-comp">
                    <div className="mq-fx-comp-desc">{c.company_profile}</div>
                    <div className="mq-fx-comp-meta">
                      <span>{c.sector}</span>
                      {c.sector_market_cap_inr?.formatted && <b>{c.sector_market_cap_inr.formatted}</b>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  )
}
