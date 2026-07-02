// Built directly off the allowlist main.py's POST /api/settings actually accepts
// (main.py:2895-2916) — not off raw config.json — so secret fields (api_key, api_secret,
// access_token, redirect_uri, proxy) are structurally impossible to add here.
//
// Three of these keys (enable_candlestick_confluence, cpc_volume_multiplier,
// enable_level_aware_targets) are accepted by the endpoint but NOT included in
// GET /api/status's snapshot, so their current value can't be read live — `defaultValue`
// below mirrors the current config.json snapshot as of this build, used only to seed the
// form; a field is only sent back to the server if the user actually changes it, so an
// unedited field never overwrites a value the UI couldn't confirm.

export type FieldType = 'bool' | 'int' | 'float' | 'time' | 'select'

export interface SettingField {
  key: string
  label: string
  type: FieldType
  hint?: string
  min?: number
  max?: number
  step?: number
  options?: string[]
  defaultValue?: unknown
}

export interface SettingGroup {
  group: string
  fields: SettingField[]
}

export const SETTINGS_SCHEMA: SettingGroup[] = [
  {
    group: 'Risk Management',
    fields: [
      { key: 'paper_trading', label: 'Paper Trading', type: 'bool', hint: 'Simulate trades locally. Disabling switches to live execution with real capital.' },
      { key: 'max_open_positions', label: 'Max Open Positions', type: 'int', min: 1, max: 20 },
      { key: 'max_daily_loss', label: 'Max Daily Loss (₹)', type: 'float', min: 0 },
      { key: 'max_weekly_loss_pct', label: 'Max Weekly Loss (%)', type: 'float', min: 0, step: 0.01 },
      { key: 'max_risk_per_trade', label: 'Max Risk Per Trade (₹)', type: 'float', min: 0 },
      { key: 'max_position_value', label: 'Max Position Value (₹)', type: 'float', min: 0 },
      { key: 'enable_one_percent_risk', label: 'Enable 1% Risk Sizing', type: 'bool' },
      { key: 'min_confidence_threshold', label: 'Min Confidence Threshold', type: 'int', min: 0, max: 100 },
      { key: 'enable_max_capacity', label: 'Enable Max Capacity Guard', type: 'bool' },
      { key: 'capacity_buffer_pct', label: 'Capacity Buffer (%)', type: 'float', min: 0, max: 1, step: 0.01 },
    ],
  },
  {
    group: 'Timing',
    fields: [
      { key: 'trade_start_time', label: 'Trade Start', type: 'time' },
      { key: 'trade_end_time', label: 'Trade End', type: 'time' },
      { key: 'square_off_time', label: 'Square-Off Time', type: 'time' },
      { key: 'enable_time_stop', label: 'Enable Time Stop', type: 'bool' },
      { key: 'time_stop_minutes', label: 'Time Stop (minutes)', type: 'int', min: 1 },
    ],
  },
  {
    group: 'Execution',
    fields: [
      { key: 'enable_trailing_stop', label: 'Enable Trailing Stop', type: 'bool' },
      { key: 'trailing_atr_multiplier', label: 'Trailing ATR Multiplier', type: 'float', min: 0, step: 0.1 },
      { key: 'enable_partial_exit_t1', label: 'Partial Exit at T1', type: 'bool' },
      { key: 'max_trades_per_symbol_per_day', label: 'Max Trades / Symbol / Day', type: 'int', min: 1 },
      { key: 'enable_vwap_trend_pullback', label: 'Enable VWAP Trend Pullback', type: 'bool' },
      { key: 'vwap_tp_confidence_threshold', label: 'VWAP Confidence Threshold', type: 'int', min: 0, max: 100 },
      { key: 'enable_candlestick_confluence', label: 'Enable Candlestick Confluence', type: 'bool', defaultValue: true },
      { key: 'cpc_volume_multiplier', label: 'Candlestick Volume Multiplier', type: 'float', min: 0, step: 0.1, defaultValue: 1.5 },
      { key: 'enable_level_aware_targets', label: 'Enable Level-Aware Targets', type: 'bool', defaultValue: true },
      { key: 'backtest_slippage_pct', label: 'Backtest Slippage (%)', type: 'float', min: 0, step: 0.0001 },
    ],
  },
  {
    group: 'Signal Quality Filters',
    fields: [
      { key: 'enable_time_filter', label: 'Time-of-Day Filter', type: 'bool' },
      { key: 'enable_volatility_filter', label: 'Volatility Filter', type: 'bool' },
      { key: 'enable_nifty_filter', label: 'Nifty Alignment Filter', type: 'bool' },
      { key: 'enable_confluence_filter', label: 'Confluence Scoring Filter', type: 'bool' },
      { key: 'min_confluence_score', label: 'Min Confluence Score', type: 'int', min: 0 },
      { key: 'enable_kelly_sizing', label: 'Kelly Sizing', type: 'bool' },
      { key: 'enable_loss_halt', label: 'Loss-Streak Circuit Breaker', type: 'bool' },
      { key: 'max_consecutive_losses', label: 'Max Consecutive Losses', type: 'int', min: 1 },
      { key: 'loss_halt_minutes', label: 'Loss Halt Duration (minutes)', type: 'int', min: 1 },
    ],
  },
  {
    group: 'F&O',
    fields: [
      { key: 'enable_fno', label: 'Enable F&O Execution', type: 'bool' },
      { key: 'fno_type', label: 'F&O Instrument Type', type: 'select', options: ['FUT', 'CE', 'PE'] },
      { key: 'option_delta', label: 'Target Option Delta', type: 'float', min: 0, max: 1, step: 0.05 },
      { key: 'fno_max_risk_per_trade', label: 'Max Risk Per Trade (₹)', type: 'float', min: 0 },
      { key: 'fno_max_lots', label: 'Max Lots', type: 'int', min: 1 },
    ],
  },
  {
    group: 'Scanning',
    fields: [
      { key: 'enable_full_market_scan', label: 'Full Market Scan', type: 'bool' },
      { key: 'scan_nse', label: 'Scan NSE', type: 'bool' },
      { key: 'scan_bse', label: 'Scan BSE', type: 'bool' },
      { key: 'min_scan_volume', label: 'Min Scan Volume', type: 'int', min: 0 },
      { key: 'min_scan_price', label: 'Min Scan Price (₹)', type: 'float', min: 0 },
      { key: 'min_scan_change_pct', label: 'Min Scan Change (%)', type: 'float', min: 0, step: 0.1 },
    ],
  },
]

export const ALL_SETTING_FIELDS: SettingField[] = SETTINGS_SCHEMA.flatMap((g) => g.fields)
