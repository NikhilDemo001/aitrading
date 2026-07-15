import { useEffect } from 'react'
import { useLiveConnection } from '../lib/ws/useLiveConnection'
import { useGlobalHotkeys } from '../lib/useGlobalHotkeys'
import { useUiStore } from '../lib/stores/useUiStore'
import { TopNav } from './TopNav'
import { SessionRibbon } from './SessionRibbon'
import { ToastLayer } from './ToastLayer'
import { AmbientBackdrop } from './AmbientBackdrop'
import { CockpitTab } from '../features/cockpit/CockpitTab'
import { AnalyticsTab } from '../features/analytics/AnalyticsTab'
import { ConfigTab } from '../features/config/ConfigTab'
import { ResearchLabTab } from '../features/research-lab/ResearchLabTab'
import { LearningTab } from '../features/learning/LearningTab'
import { NewsTab } from '../features/news/NewsTab'
import { FundamentalsTab } from '../features/fundamentals/FundamentalsTab'
import { StatusBar } from './StatusBar'
import './App.css'

export default function App() {
  useLiveConnection()
  useGlobalHotkeys()
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)

  // Deep-linking: a URL landing on #/learning?... (bookmarked/shared from the Learning
  // tab's date-range controls) should open directly into that tab, not just update the
  // hash silently while some other tab is showing.
  useEffect(() => {
    const syncFromHash = () => {
      if (window.location.hash.startsWith('#/learning')) setActiveTab('learning')
    }
    syncFromHash()
    window.addEventListener('hashchange', syncFromHash)
    return () => window.removeEventListener('hashchange', syncFromHash)
  }, [setActiveTab])

  return (
    <div className="mq-app">
      <AmbientBackdrop />
      <TopNav />
      <SessionRibbon />
      <ToastLayer />
      <main
        className="mq-main"
        id="mq-tabpanel"
        role="tabpanel"
        aria-labelledby={`mq-tab-${activeTab}`}
      >
        {activeTab === 'cockpit' && <CockpitTab />}
        {activeTab === 'analytics' && <AnalyticsTab />}
        {activeTab === 'config' && <ConfigTab />}
        {activeTab === 'research-lab' && <ResearchLabTab />}
        {activeTab === 'learning' && <LearningTab />}
        {activeTab === 'news' && <NewsTab />}
        {activeTab === 'fundamentals' && <FundamentalsTab />}
      </main>
      <StatusBar />
    </div>
  )
}
