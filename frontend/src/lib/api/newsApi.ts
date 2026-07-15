import { http } from './http'

export interface NewsItem {
  heading: string
  summary: string
  published: number | null
  link: string
}

// Recent (7-day) news for a symbol — the same feed the LLM entry gate reasons over.
export const newsApi = {
  getNews: (symbol: string) => http.get<NewsItem[]>(`/api/news/${encodeURIComponent(symbol)}`),
}
