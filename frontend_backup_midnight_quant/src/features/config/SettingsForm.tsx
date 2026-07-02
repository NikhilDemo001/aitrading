import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { statusApi } from '../../lib/api/statusApi'
import { settingsApi } from '../../lib/api/settingsApi'
import { SETTINGS_SCHEMA, ALL_SETTING_FIELDS, type SettingField } from './settingsSchema'
import './SettingsForm.css'

type Draft = Record<string, unknown>

function initialDraft(status: Record<string, unknown> | null): Draft {
  const draft: Draft = {}
  for (const field of ALL_SETTING_FIELDS) {
    draft[field.key] = status?.[field.key] ?? field.defaultValue
  }
  return draft
}

function FieldInput({ field, value, onChange }: { field: SettingField; value: unknown; onChange: (v: unknown) => void }) {
  if (field.type === 'bool') {
    return (
      <button
        type="button"
        className={`mq-field-toggle ${value ? 'on' : ''}`}
        onClick={() => onChange(!value)}
        aria-pressed={!!value}
      >
        <span className="mq-field-toggle-knob" />
      </button>
    )
  }
  if (field.type === 'select') {
    return (
      <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
        {field.options?.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
      </select>
    )
  }
  if (field.type === 'time') {
    return <input type="time" value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
  }
  // int | float
  return (
    <input
      type="number"
      min={field.min}
      max={field.max}
      step={field.step ?? (field.type === 'int' ? 1 : 0.01)}
      value={value == null ? '' : String(value)}
      onChange={(e) => onChange(field.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value))}
    />
  )
}

export function SettingsForm() {
  // Deliberately NOT sourced from the live WS-pushed status in useBotStore: main.py's
  // `/ws` init payload (main.py:330-370) is a hand-maintained subset of fields that has
  // drifted out of sync with the full get_status() used by GET /api/status — it's
  // missing min_confidence_threshold, capacity_buffer_pct, enable_max_capacity, and about
  // a dozen other settable fields. A one-shot REST fetch here gets the authoritative,
  // complete snapshot this form needs to edit safely.
  const { data: fullStatus } = useQuery({
    queryKey: ['status', 'full-for-settings'],
    queryFn: statusApi.getStatus,
    staleTime: Infinity,
  })
  const [draft, setDraft] = useState<Draft | null>(null)
  const [query, setQuery] = useState('')
  const [savedAt, setSavedAt] = useState<number | null>(null)

  // Seed the draft once the full status snapshot first arrives; further refetches don't
  // clobber in-progress edits.
  useEffect(() => {
    if (draft === null && fullStatus) setDraft(initialDraft(fullStatus as Record<string, unknown>))
  }, [fullStatus, draft])

  const mutation = useMutation({
    mutationFn: (payload: Draft) => settingsApi.save(payload),
    onSuccess: () => setSavedAt(Date.now()),
  })

  const filteredSchema = useMemo(() => {
    if (!query.trim()) return SETTINGS_SCHEMA
    const q = query.toLowerCase()
    return SETTINGS_SCHEMA.map((g) => ({
      group: g.group,
      fields: g.fields.filter((f) => f.label.toLowerCase().includes(q) || f.key.includes(q)),
    })).filter((g) => g.fields.length > 0)
  }, [query])

  if (!draft) {
    return (
      <Panel title="Settings">
        <p className="text-faint">Loading current configuration…</p>
      </Panel>
    )
  }

  return (
    <div className="mq-settings">
      <div className="mq-settings-searchbar">
        <input placeholder="Search settings…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Button variant="primary" disabled={mutation.isPending} onClick={() => mutation.mutate(draft)}>
          {mutation.isPending ? 'Saving…' : 'Save All Settings'}
        </Button>
        {savedAt && Date.now() - savedAt < 4000 && <span className="mq-settings-saved text-profit">Saved</span>}
      </div>

      {filteredSchema.map((g) => (
        <Panel key={g.group} title={g.group}>
          <div className="mq-settings-grid">
            {g.fields.map((field) => (
              <div key={field.key} className="mq-settings-field" title={field.hint}>
                <span className="mq-settings-label">{field.label}</span>
                <FieldInput field={field} value={draft[field.key]} onChange={(v) => setDraft((d) => ({ ...d!, [field.key]: v }))} />
              </div>
            ))}
          </div>
        </Panel>
      ))}
    </div>
  )
}
