export type CoachChatIntent = 'sunday_review' | 'today_run'

export interface CoachChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  client_message_id: string | null
}

export interface CoachChat {
  id: string | null
  status: 'idle' | 'running' | 'cancelled' | 'failed'
  messages: CoachChatMessage[]
  error: { code: string; message: string } | null
  proposal_id: string | null
  proposal_revision: number | null
}

export interface CoachChatSend {
  text: string
  client_message_id: string
  thread_id: string | null
  intent?: CoachChatIntent
}

export interface CoachAuth {
  status: 'idle' | 'waiting' | 'signed_in' | 'signed_out' | 'failed' | 'cancelled'
  url: string | null
  error: { code: string; message: string } | null
}
