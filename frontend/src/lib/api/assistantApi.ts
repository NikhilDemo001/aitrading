import { http } from './http'

export interface AssistantTurn { role: 'user' | 'assistant'; content: string }
export interface AssistantReply { answer: string; source: string }

export const assistantApi = {
  ask: (question: string, history: AssistantTurn[]) =>
    http.post<AssistantReply>('/api/assistant/ask', { question, history }),
}
