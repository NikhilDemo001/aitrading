import { useQuery } from '@tanstack/react-query'
import { useBotStore } from '../lib/stores/useBotStore'
import { usePositionsStore } from '../lib/stores/usePositionsStore'
import { useScannerStore } from '../lib/stores/useScannerStore'
import { systemApi } from '../lib/api/systemApi'
import './StatusBar.css'

// Always-on telemetry ribbon: pulls together live state that would otherwise be scattered
// or invisible — WS transport, broker IP/proxy, LLM engine budget, scanner cadence — so the
// operator has a single glanceable "is everything healthy" strip at all times.
export function StatusBar() {
  const connected = useBotStore((s) => s.connected)
  const status = useBotStore((s) => s.status)
  const positions = usePositionsStore((s) => s.positions)
  const scannerMatrix = useScannerStore((s) => s.scanner.matrix)

  const { data: llm } = useQuery({ queryKey: ['llm-status'], queryFn: systemApi.getLlmStatus, refetchInterval: 30000 })
  const { data: ipData } = useQuery({ queryKey: ['my-ip'], queryFn: systemApi.getMyIp, refetchInterval: 120000, retry: 0 })

  const item = (label: string, value: React.ReactNode, tone?: 'profit' | 'loss' | 'warn' | 'accent') => (
    <div className="mq-sb-item">
      <span className="mq-sb-label">{label}</span>
      <span className={`mq-sb-value num ${tone ? `text-${tone}` : ''}`}>{value}</span>
    </div>
  )

  return (
    <footer className="mq-statusbar">
      {item('LINK', connected ? 'WS LIVE' : 'POLLING', connected ? 'profit' : 'warn')}
      {item('MODE', status?.paper_trading ? 'PAPER' : 'LIVE', status?.paper_trading ? 'accent' : 'warn')}
      {item('POS', `${positions.length}/${status?.max_open_positions ?? '—'}`)}
      {item('SCAN', `${scannerMatrix.length} sym`)}
      {item('IP', ipData?.ip ?? '—')}
      {item(
        'LLM',
        llm ? (llm.enabled ? `ON · ${llm.budget_remaining}/${llm.daily_cap}` : 'OFF') : '—',
        llm?.enabled ? 'profit' : undefined,
      )}
      {item('MODEL', llm?.model ?? '—')}
      <div className="mq-sb-spacer" />
      <div className="mq-sb-item mq-sb-brand">MIDNIGHT·QUANT · NSE INTRADAY · UPSTOX V3</div>
    </footer>
  )
}
