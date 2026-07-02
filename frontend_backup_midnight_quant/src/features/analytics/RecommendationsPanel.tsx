import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { analyticsApi } from '../../lib/api/analyticsApi'
import './RecommendationsPanel.css'

export function RecommendationsPanel() {
  const { data } = useQuery({
    queryKey: ['analytics', 'report'],
    queryFn: analyticsApi.getReport,
    refetchInterval: 15000,
  })
  const recommendations = ((data as { insights?: { recommendations?: string[] } } | undefined)?.insights?.recommendations) ?? []

  return (
    <Panel title="System Recommendations">
      <ul className="mq-reco-list">
        {recommendations.map((r, i) => <li key={i}>{r}</li>)}
      </ul>
    </Panel>
  )
}
