import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useBotStore, EMPTY_WATCHLIST } from '../../lib/stores/useBotStore'
import { newsApi } from '../../lib/api/newsApi'
import './NewsTab.css'

function timeAgo(ms?: number | null): string {
  if (!ms) return ''
  const diff = Date.now() - ms
  if (diff < 3_600_000) return `${Math.max(1, Math.floor(diff / 60_000))}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

export function NewsTab() {
  const watchlist = useBotStore((s) => s.status?.watchlist ?? EMPTY_WATCHLIST)
  const [symbol, setSymbol] = useState<string | null>(null)
  const active = symbol ?? watchlist[0] ?? null

  const { data, isLoading, isError } = useQuery({
    queryKey: ['news-tab', active],
    queryFn: () => newsApi.getNews(active as string),
    enabled: !!active,
    refetchInterval: 300_000,
    retry: 0,
  })

  return (
    <div className="mq-newstab">
      <div className="mq-newstab-head">
        <div>
          <h2 className="mq-newstab-title">Market News</h2>
          <p className="mq-newstab-sub">Past 7 days · the same feed the AI entry gate reads</p>
        </div>
        <label className="mq-newstab-picker">
          <span>Symbol</span>
          <select value={active ?? ''} onChange={(e) => setSymbol(e.target.value)}>
            {watchlist.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>

      {!active ? (
        <div className="mq-newstab-empty">No symbol selected.</div>
      ) : isLoading ? (
        <div className="mq-newstab-empty">Fetching news for {active}…</div>
      ) : isError ? (
        <div className="mq-newstab-empty">Couldn't load news — check the Upstox session.</div>
      ) : !data || data.length === 0 ? (
        <div className="mq-newstab-empty">No news for {active} in the last 7 days.</div>
      ) : (
        <div className="mq-newstab-grid">
          {data.map((n, i) => (
            <article key={i} className="mq-newscard">
              <div className="mq-newscard-time">{timeAgo(n.published)}</div>
              {n.link ? (
                <a href={n.link} target="_blank" rel="noreferrer" className="mq-newscard-head">{n.heading}</a>
              ) : (
                <span className="mq-newscard-head">{n.heading}</span>
              )}
              {n.summary && <p className="mq-newscard-summary">{n.summary}</p>}
              {n.link && (
                <a href={n.link} target="_blank" rel="noreferrer" className="mq-newscard-link">
                  Read full article →
                </a>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
