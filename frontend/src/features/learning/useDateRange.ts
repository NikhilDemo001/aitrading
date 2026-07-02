import { useCallback, useEffect, useState } from 'react'

export interface DateRangeState {
  start: string
  end: string
  singleDay: boolean
  asOf: string
}

export type DateRangePreset = 'today' | 'yesterday' | 'last5' | 'week' | 'month' | 'last30' | 'all'

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function daysAgoIso(n: number) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

const DEFAULT_STATE: DateRangeState = { start: daysAgoIso(30), end: todayIso(), singleDay: false, asOf: '' }

// Hand-rolled hash sync (no react-router needed for a single tab's state): reads
// `#/learning?start=...&end=...&singleDay=...&asOf=...` on mount and keeps it updated on
// every change, so the Learning tab's range is bookmarkable/shareable and survives reload,
// matching the legacy tab's deep-linking behavior.
function readFromHash(): DateRangeState | null {
  const hash = window.location.hash
  const qIndex = hash.indexOf('?')
  if (qIndex === -1) return null
  const params = new URLSearchParams(hash.slice(qIndex + 1))
  if (![...params.keys()].length) return null
  return {
    start: params.get('start') ?? DEFAULT_STATE.start,
    end: params.get('end') ?? DEFAULT_STATE.end,
    singleDay: params.get('singleDay') === 'true',
    asOf: params.get('asOf') ?? '',
  }
}

function writeToHash(state: DateRangeState) {
  const params = new URLSearchParams({
    start: state.start,
    end: state.end,
    singleDay: String(state.singleDay),
    asOf: state.asOf,
  })
  window.location.hash = `/learning?${params.toString()}`
}

export function useDateRange() {
  const [range, setRangeState] = useState<DateRangeState>(() => readFromHash() ?? DEFAULT_STATE)

  useEffect(() => {
    writeToHash(range)
  }, [range])

  useEffect(() => {
    const onHashChange = () => {
      const next = readFromHash()
      if (next) setRangeState(next)
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const setRange = useCallback((partial: Partial<DateRangeState>) => {
    setRangeState((prev) => ({ ...prev, ...partial }))
  }, [])

  const applyPreset = useCallback((preset: DateRangePreset) => {
    const end = todayIso()
    switch (preset) {
      case 'today': setRange({ start: end, end, singleDay: true, asOf: '' }); break
      case 'yesterday': { const y = daysAgoIso(1); setRange({ start: y, end: y, singleDay: true, asOf: '' }); break }
      case 'last5': setRange({ start: daysAgoIso(5), end, singleDay: false, asOf: '' }); break
      case 'week': setRange({ start: daysAgoIso(7), end, singleDay: false, asOf: '' }); break
      case 'month': setRange({ start: daysAgoIso(30), end, singleDay: false, asOf: '' }); break
      case 'last30': setRange({ start: daysAgoIso(30), end, singleDay: false, asOf: '' }); break
      case 'all': setRange({ start: '2020-01-01', end, singleDay: false, asOf: '' }); break
    }
  }, [setRange])

  return { range, setRange, applyPreset }
}
