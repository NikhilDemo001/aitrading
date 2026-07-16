import { useBotStore } from '../lib/stores/useBotStore'
import { useUiStore, type TabId } from '../lib/stores/useUiStore'
import { Button } from '../design-system/Button'
import { statusApi } from '../lib/api/statusApi'
import './TopNav.css'

const TABS: { id: TabId; label: string }[] = [
  { id: 'cockpit', label: 'Cockpit' },
  { id: 'trades', label: 'Trades' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'config', label: 'Config' },
  { id: 'research-lab', label: 'AI Research Lab' },
  { id: 'learning', label: 'Learning' },
  { id: 'news', label: 'News' },
  { id: 'fundamentals', label: 'Fundamentals' },
  { id: 'assistant', label: 'Assistant' },
]

export function TopNav() {
  const status = useBotStore((s) => s.status)
  const connected = useBotStore((s) => s.connected)
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)

  const authenticated = status?.authenticated ?? false
  const botRunning = status?.bot_running ?? false
  const paperTrading = status?.paper_trading ?? true
  const scanLastLoop = (status?.scanner_last_loop as string | null) ?? null
  const scanLastChecked = (status?.scanner_last_checked as string | null) ?? null

  const handleToggleBot = () => statusApi.toggle().catch(console.error)
  const handleSquareOff = () => {
    if (confirm('Square off all open positions now?')) statusApi.squareOff().catch(console.error)
  }
  const handleKill = () => {
    if (confirm('EMERGENCY KILL: halt the bot and square off ALL open positions immediately. Continue?')) {
      statusApi.killSwitch().catch(console.error)
    }
  }

  return (
    <header className="mq-topnav">
      <div className="mq-topnav-row1">
        <div className="mq-brand">
          <div className="mq-brand-mark">CT</div>
          <div className="mq-brand-text">
            <span className="mq-brand-name neon-text">CIPHER · TERMINAL</span>
            <span className="mq-brand-sub">UPSTOX INTRADAY AUTOPILOT</span>
          </div>
        </div>

        <div className="mq-led-strip" role="status" aria-label="System status">
          <span className="mq-led" title="Server / live WebSocket connection">
            <span className={`led ${connected ? 'led-green led-pulse' : 'led-magenta'}`} /> <span className="mq-led-text">{connected ? 'WS' : 'POLL'}</span>
          </span>
          <span className="mq-led" title="Broker API">
            <span className={`led ${authenticated ? 'led-green' : 'led-off'}`} /> <span className="mq-led-text">API</span>
          </span>
          <span className="mq-led" title={paperTrading ? 'Paper trading (simulated)' : 'LIVE trading (real capital)'}>
            <span className={`led ${paperTrading ? 'led-cyan' : 'led-crimson led-pulse'}`} /> <span className="mq-led-text">{paperTrading ? 'PAPER' : 'LIVE'}</span>
          </span>
          <span className="mq-led" title="Bot engine">
            <span className={`led ${botRunning ? 'led-cyan led-pulse' : 'led-off'}`} /> <span className="mq-led-text">BOT</span>
          </span>
          <span className="mq-led" title="Last scanner sweep">
            <span className={`led ${scanLastLoop ? 'led-cyan' : 'led-off'}`} /> <span className="mq-led-text num">{scanLastLoop ?? '—'}</span>
          </span>
          <span className="mq-led" title="Last symbol checked">
            <span className="led led-amber" /> <span className="mq-led-text">{scanLastChecked ?? '—'}</span>
          </span>
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
          <Button variant="kill" onClick={handleKill} title="Emergency stop — halt bot and square off all positions">
            <span className="mq-btn-full">Kill Switch</span>
            <span className="mq-btn-short">KILL</span>
          </Button>
        </div>
      </div>

      <nav className="mq-tabnav" role="tablist" aria-label="Dashboard sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`mq-tab-${t.id}`}
            role="tab"
            aria-selected={activeTab === t.id}
            aria-controls="mq-tabpanel"
            tabIndex={activeTab === t.id ? 0 : -1}
            className={`mq-tab-btn ${activeTab === t.id ? 'active' : ''}`}
            onClick={() => setActiveTab(t.id)}
            onKeyDown={(e) => {
              // WAI-ARIA APG tabs pattern: roving tabindex + arrow-key navigation.
              // Position comes from the tab the event fired on (not React state), so
              // rapid key-repeat can't act on a stale activeTab mid-render.
              const idx = TABS.findIndex((x) => `mq-tab-${x.id}` === e.currentTarget.id)
              let next = -1
              if (e.key === 'ArrowRight') next = (idx + 1) % TABS.length
              else if (e.key === 'ArrowLeft') next = (idx - 1 + TABS.length) % TABS.length
              else if (e.key === 'Home') next = 0
              else if (e.key === 'End') next = TABS.length - 1
              if (next >= 0) {
                e.preventDefault()
                setActiveTab(TABS[next].id)
                document.getElementById(`mq-tab-${TABS[next].id}`)?.focus()
              }
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </header>
  )
}
