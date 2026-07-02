import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { researchApi } from '../../lib/api/researchApi'
import './TimelineHypotheses.css'

export function TimelineHypotheses() {
  const { data: briefing } = useQuery({ queryKey: ['research', 'briefing'], queryFn: researchApi.getBriefing })
  const { data: timeline } = useQuery({ queryKey: ['research', 'timeline'], queryFn: () => researchApi.getTimeline() })
  const { data: hypotheses } = useQuery({ queryKey: ['research', 'hypotheses'], queryFn: researchApi.getHypotheses })

  return (
    <div className="mq-timeline-layout">
      {briefing && (
        <Panel title="Voice of the AI">
          <p className="mq-voice-text">{briefing.voice_of_ai}</p>
          <p className="text-faint mq-voice-market">{briefing.market_summary}</p>
        </Panel>
      )}

      <div className="mq-timeline-cols">
        <Panel title="Timeline" padded={false}>
          <div className="mq-timeline-list">
            {(timeline ?? []).map((ev, i) => (
              <div key={i} className="mq-timeline-item">
                <div className="mq-timeline-item-hdr">
                  <Badge tone="accent">{ev.type}</Badge>
                  <span className="text-faint">{ev.created_at}</span>
                </div>
                <div className="mq-timeline-title">{ev.title}</div>
                {ev.improvement && <div className="mq-timeline-detail">{ev.improvement}</div>}
                {ev.result && <div className="mq-timeline-result text-profit">{ev.result}</div>}
              </div>
            ))}
            {(timeline ?? []).length === 0 && <div className="text-faint mq-timeline-empty">No events yet.</div>}
          </div>
        </Panel>

        <Panel title="Hypotheses" padded={false}>
          <div className="mq-timeline-list">
            {(hypotheses ?? []).map((h) => (
              <div key={h.id} className="mq-timeline-item">
                <div className="mq-timeline-item-hdr">
                  <span className="mq-timeline-title">{h.name}</span>
                  <span className="num text-faint">{h.current_score.toFixed(1)}</span>
                </div>
                <div className="mq-timeline-detail">{h.pattern_description}</div>
              </div>
            ))}
            {(hypotheses ?? []).length === 0 && <div className="text-faint mq-timeline-empty">No hypotheses yet.</div>}
          </div>
        </Panel>
      </div>
    </div>
  )
}
