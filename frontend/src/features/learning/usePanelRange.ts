import { useMemo, useState } from 'react'
import { presetRange, type DateRangeState, type DateRangePreset } from './useDateRange'

export type PanelPreset = 'global' | DateRangePreset

/** A panel's own date filter. Defaults to the tab-wide range, so nothing changes until the
 *  operator pins this panel to its own period — letting them, say, watch the 30-day KPI trend
 *  while drilling into just today's trades. */
export function usePanelRange(global: DateRangeState) {
  const [override, setOverride] = useState<PanelPreset>('global')
  const range = useMemo(
    () => (override === 'global' ? global : presetRange(override)),
    [override, global],
  )
  return { range, override, setOverride }
}
