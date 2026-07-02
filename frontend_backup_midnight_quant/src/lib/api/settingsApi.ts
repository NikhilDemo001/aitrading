import { http } from './http'

export const settingsApi = {
  save: (partial: Record<string, unknown>) => http.post('/api/settings', partial),
}
