import { useState } from 'react'
import { SandboxPipeline } from './SandboxPipeline'
import { CtoChat } from './CtoChat'
import { Marketplace } from './Marketplace'
import { CompareCenter } from './CompareCenter'
import { RiskAndCapital } from './RiskAndCapital'
import { TimelineHypotheses } from './TimelineHypotheses'
import { LaneBPanel } from './LaneBPanel'
import './ResearchLabTab.css'

type SubTab = 'sandbox' | 'chat' | 'marketplace' | 'compare' | 'risk' | 'timeline' | 'laneb'

const SUB_TABS: Array<{ id: SubTab; label: string }> = [
  { id: 'sandbox', label: 'Sandbox Pipeline' },
  { id: 'chat', label: 'AI CTO Chat' },
  { id: 'marketplace', label: 'Marketplace' },
  { id: 'compare', label: 'Compare Center' },
  { id: 'risk', label: 'Risk & Capital' },
  { id: 'timeline', label: 'Timeline & Hypotheses' },
  { id: 'laneb', label: 'Lane B · LLM' },
]

export function ResearchLabTab() {
  const [sub, setSub] = useState<SubTab>('sandbox')

  return (
    <div className="mq-rlab">
      <nav className="mq-rlab-subnav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={`mq-rlab-subtab ${sub === t.id ? 'active' : ''}`} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <div className="mq-rlab-body">
        {sub === 'sandbox' && <SandboxPipeline />}
        {sub === 'chat' && <CtoChat />}
        {sub === 'marketplace' && <Marketplace />}
        {sub === 'compare' && <CompareCenter />}
        {sub === 'risk' && <RiskAndCapital />}
        {sub === 'timeline' && <TimelineHypotheses />}
        {sub === 'laneb' && <LaneBPanel />}
      </div>
    </div>
  )
}
