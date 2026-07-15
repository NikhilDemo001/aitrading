import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { newsApi } from '../../lib/api/newsApi'
import './NewsPanel.css'

// Recent news for the charted symbol — the exact catalysts the LLM entry gate weighs
// before confirming a live entry. Read-only; refreshes every 5 minutes.

function timeAgo(ms?: number | null): string {
  if (!ms) return ''
  const diff = Date.now() - ms
  if (diff < 3_600_000) return `${Math.max(1, Math.floor(diff / 60_000))}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

export function NewsPanel({ symbol }: { symbol: string | null }) {
  const { data, isLoading } = useQuery({
    queryKey: ['news', symbol],
    queryFn: () => newsApi.getNews(symbol as string),
    enabled: !!symbol,
    refetchInterval: 300_000,
    retry: 0,
  })

  return (
    <Panel title={`News · ${symbol ?? '—'}`} padded={false}>
      {!symbol ? (
        <div className="mq-news-empty text-faint">Select a symbol to see its news.</div>
      ) : isLoading ? (
        <div className="mq-news-empty text-faint">Fetching news…</div>
      ) : !data || data.length === 0 ? (
        <div className="mq-news-empty text-faint">No news in the last 7 days.</div>
      ) : (
        <ul className="mq-news-list">
          {data.map((n, i) => (
            <li key={i} className="mq-news-item">
              {n.link ? (
                <a href={n.link} target="_blank" rel="noreferrer" className="mq-news-head">
                  {n.heading}
                </a>
              ) : (
                <span className="mq-news-head">{n.heading}</span>
              )}
              <div className="mq-news-meta text-faint">{timeAgo(n.published)}</div>
              {n.summary && <div className="mq-news-summary text-faint">{n.summary}</div>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
