import { useMemo, useState } from 'react'
import { Panel } from '../../design-system/Panel'
import { useLogsStore } from '../../lib/stores/useLogsStore'
import './LiveFeedPanel.css'

type FilterTag = 'all' | 'signals' | 'errors'

export function LiveFeedPanel() {
  const logs = useLogsStore((s) => s.logs)
  const [filter, setFilter] = useState<FilterTag>('all')
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    return logs.filter((log) => {
      const message = String(log.message ?? '')
      if (query && !message.toLowerCase().includes(query.toLowerCase())) return false
      if (filter === 'signals') return /signal|entry|exit|trade/i.test(message)
      if (filter === 'errors') return /error|fail|reject/i.test(message)
      return true
    })
  }, [logs, filter, query])

  return (
    <Panel
      title="Live Feed"
      padded={false}
      className="mq-feed-panel"
      actions={
        <div className="mq-feed-filters">
          {(['all', 'signals', 'errors'] as FilterTag[]).map((tag) => (
            <button key={tag} className={`mq-feed-filter ${filter === tag ? 'active' : ''}`} onClick={() => setFilter(tag)}>
              {tag}
            </button>
          ))}
        </div>
      }
    >
      <div className="mq-feed-search">
        <input placeholder="Search feed..." value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div className="mq-feed-list">
        {filtered.length === 0 && <div className="mq-feed-empty text-faint">No activity yet.</div>}
        {filtered.map((log, i) => (
          <div key={i} className="mq-feed-row">
            <span className="mq-feed-time num">{log.time ?? ''}</span>
            <span className="mq-feed-msg">{String(log.message ?? '')}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
