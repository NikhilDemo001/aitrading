import { useEffect } from 'react'
import { useUiStore, type TabId } from './stores/useUiStore'
import { statusApi } from './api/statusApi'

const TAB_KEYS: Record<string, TabId> = {
  '1': 'cockpit',
  '2': 'analytics',
  '3': 'config',
  '4': 'research-lab',
  '5': 'learning',
}

function isTypingTarget(target: EventTarget | null) {
  const el = target as HTMLElement | null
  return !!el && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

export function useGlobalHotkeys() {
  const setActiveTab = useUiStore((s) => s.setActiveTab)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return
      if (e.key in TAB_KEYS) {
        setActiveTab(TAB_KEYS[e.key])
      } else if (e.key === 'Escape') {
        // Escape also closes dialogs — never treat it as square-off while one is open,
        // even if the dialog's own handler failed to swallow the event.
        if (document.querySelector('[role="dialog"]')) return
        if (confirm('Square off all open positions now?')) {
          statusApi.squareOff().catch(console.error)
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [setActiveTab])
}
