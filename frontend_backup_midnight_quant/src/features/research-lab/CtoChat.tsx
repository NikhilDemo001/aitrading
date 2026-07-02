import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { researchApi } from '../../lib/api/researchApi'
import './CtoChat.css'

interface ChatMessage {
  query: string
  title: string
  text: string
}

export function CtoChat() {
  const [query, setQuery] = useState('')
  const [history, setHistory] = useState<ChatMessage[]>([])

  const mutation = useMutation({
    mutationFn: (q: string) => researchApi.chat(q),
    onSuccess: (res, q) => setHistory((h) => [...h, { query: q, title: res.title, text: res.text }]),
  })

  const send = () => {
    const q = query.trim()
    if (!q) return
    mutation.mutate(q)
    setQuery('')
  }

  return (
    <Panel title="AI CTO Chat">
      <div className="mq-chat-history">
        {history.length === 0 && <p className="text-faint">Ask about strategy performance, risk, or what the lab is working on.</p>}
        {history.map((m, i) => (
          <div key={i} className="mq-chat-turn">
            <div className="mq-chat-query">{m.query}</div>
            <div className="mq-chat-reply">
              <span className="mq-chat-persona">{m.title}</span>
              <p>{m.text}</p>
            </div>
          </div>
        ))}
        {mutation.isPending && <div className="mq-chat-turn text-faint">Thinking…</div>}
      </div>
      <div className="mq-chat-input">
        <input
          placeholder="e.g. what's the best performing strategy right now?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <Button variant="primary" onClick={send} disabled={!query.trim() || mutation.isPending}>Send</Button>
      </div>
    </Panel>
  )
}
