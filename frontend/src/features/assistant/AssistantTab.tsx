import { useRef, useState } from 'react'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { assistantApi, type AssistantTurn } from '../../lib/api/assistantApi'
import './AssistantTab.css'

const SUGGESTIONS = [
  'How did today go?',
  'Why are there no trades today?',
  'Which strategy is losing money?',
  'What are my open positions doing?',
]

export function AssistantTab() {
  const [turns, setTurns] = useState<AssistantTurn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  const send = async (q: string) => {
    const question = q.trim()
    if (!question || busy) return
    const history = turns.slice(-6)
    setTurns((t) => [...t, { role: 'user', content: question }])
    setInput('')
    setBusy(true)
    try {
      const reply = await assistantApi.ask(question, history)
      setTurns((t) => [...t, { role: 'assistant', content: reply.answer }])
    } catch (e) {
      setTurns((t) => [...t, { role: 'assistant', content: `Error: ${(e as Error).message}` }])
    } finally {
      setBusy(false)
      requestAnimationFrame(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }))
    }
  }

  return (
    <Panel title="Assistant · ask your bot">
      <div className="mq-assist">
        {turns.length === 0 ? (
          <div className="mq-assist-empty text-faint">
            <p>Ask about your bot's decisions, performance, positions, or strategies. Read-only — I can't place trades.</p>
            <div className="mq-assist-suggest">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="mq-assist-chip" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mq-assist-log">
            {turns.map((t, i) => (
              <div key={i} className={`mq-assist-msg mq-assist-${t.role}`}>
                <span className="mq-assist-role">{t.role === 'user' ? 'You' : 'Bot'}</span>
                <div className="mq-assist-text">{t.content}</div>
              </div>
            ))}
            {busy && (
              <div className="mq-assist-msg mq-assist-assistant">
                <span className="mq-assist-role">Bot</span>
                <div className="mq-assist-text text-faint">thinking…</div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        )}
        <form className="mq-assist-input" onSubmit={(e) => { e.preventDefault(); send(input) }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask your bot…"
            aria-label="Ask your bot"
            disabled={busy}
          />
          <Button variant="success" onClick={() => send(input)}>Send</Button>
        </form>
      </div>
    </Panel>
  )
}
