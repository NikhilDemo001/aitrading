import { useBotStore } from '../lib/stores/useBotStore'
import { useUiStore, type TabId } from '../lib/stores/useUiStore'
import { StatusDot } from '../design-system/Badge'
import { Button } from '../design-system/Button'
import { statusApi } from '../lib/api/statusApi'
import './TopNav.css'

const TABS: { id: TabId; label: string }[] = [
  { id: 'cockpit', label: 'Cockpit' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'config', label: 'Config' },
  { id: 'research-lab', label: 'AI Research Lab' },
  { id: 'learning', label: 'Learning' },
]

export function TopNav() {
  const status = useBotStore((s) => s.status)
  const connected = useBotStore((s) => s.connected)
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)

  const authenticated = status?.authenticated ?? false
  const botRunning = status?.bot_running ?? false
  const paperTrading = status?.paper_trading ?? true

  const handleToggleBot = () => statusApi.toggle().catch(console.error)
  const handleSquareOff = () => {
    if (confirm('Square off all open positions now?')) statusApi.squareOff().catch(console.error)
  }

  return (
    <header className="mq-topnav">
      <div className="mq-topnav-row1">
        <div className="mq-brand">
          <div className="mq-brand-mark">MQ</div>
          <div className="mq-brand-text">
            <span className="mq-brand-name">MIDNIGHT · QUANT</span>
            <span className="mq-brand-sub">UPSTOX INTRADAY AUTOPILOT</span>
          </div>
        </div>

        <div className="mq-led-strip" role="status" aria-label="System status">
          <span className="mq-led" title="Server / live connection"><StatusDot tone={connected ? 'profit' : 'loss'} pulse={connected} /> <span className="mq-led-text">SRV</span></span>
          <span className="mq-led" title="Broker API"><StatusDot tone={authenticated ? 'profit' : 'neutral'} /> <span className="mq-led-text">API</span></span>
          <span className="mq-led" title={paperTrading ? 'Paper trading' : 'Live trading'}><StatusDot tone={paperTrading ? 'info' : 'warn'} /> <span className="mq-led-text">{paperTrading ? 'PAPER' : 'LIVE'}</span></span>
          <span className="mq-led" title="Bot engine"><StatusDot tone={botRunning ? 'accent' : 'neutral'} pulse={botRunning} /> <span className="mq-led-text">BOT</span></span>
        </div>

        <div className="mq-nav-actions">
          <Button variant="ghost" onClick={() => (window.location.href = '/login')}>
            {authenticated ? 'Connected' : 'Connect'}
          </Button>
          <Button variant={botRunning ? 'danger' : 'success'} onClick={handleToggleBot}>
            <span className="mq-btn-full">{botRunning ? 'Stop Bot' : 'Start Bot'}</span>
            <span className="mq-btn-short">{botRunning ? 'Stop' : 'Start'}</span>
          </Button>
          <Button variant="danger" onClick={handleSquareOff}>
            <span className="mq-btn-full">Square Off</span>
            <span className="mq-btn-short">Sq Off</span>
          </Button>
        </div>
      </div>

      <nav className="mq-tabnav" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={activeTab === t.id}
            className={`mq-tab-btn ${activeTab === t.id ? 'active' : ''}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </header>
  )
}
