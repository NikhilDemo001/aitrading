import './SymbolSearch.css'

interface Props {
  value: string | null
  options: string[]
  onPick: (symbol: string) => void
  id?: string
}

// Type-to-search symbol input with watchlist autocomplete. Commits on Enter, on blur,
// or when a suggestion is picked — never per keystroke (so it doesn't spam the API).
// Accepts any typed symbol, not just the watchlist.
export function SymbolSearch({ value, options, onPick, id = 'mq-sym-options' }: Props) {
  const commit = (raw: string) => {
    const s = raw.trim().toUpperCase()
    if (s && s !== value) onPick(s)
  }
  return (
    <div className="mq-symsearch">
      <span className="mq-symsearch-icon" aria-hidden>⌕</span>
      <input
        key={value ?? ''}
        list={id}
        defaultValue={value ?? ''}
        placeholder="Search symbol…"
        autoComplete="off"
        spellCheck={false}
        aria-label="Search symbol"
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(e.currentTarget.value) } }}
        onChange={(e) => { const v = e.target.value.trim().toUpperCase(); if (options.includes(v)) commit(v) }}
        onBlur={(e) => commit(e.target.value)}
      />
      <datalist id={id}>
        {options.map((s) => <option key={s} value={s} />)}
      </datalist>
    </div>
  )
}
