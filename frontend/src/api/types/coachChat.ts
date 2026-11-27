import type { components } from '../generated/coachChat'

type Schemas = components['schemas']

export type CoachChat = Schemas['ChatView']
export type CoachChatMessage = Schemas['ChatMessage']
// The dashboard always fences sends to the displayed review, including the initial null ID.
export type CoachChatSend = Schemas['MessageInput'] &
  Required<Pick<Schemas['ReviewInput'], 'thread_id'>>
export type CoachChatIntent = NonNullable<CoachChatSend['intent']>
export type CoachAuth = Schemas['AuthView']
