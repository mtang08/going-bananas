import type { CoachChatIntent } from '../api/types/coachChat'

export const pageHref = {
  home: '#home',
  coach: '#coach',
  coachStart: (intent: CoachChatIntent) => `#coach/${intent}`,
  proposal: (id: string) => `#proposal/${encodeURIComponent(id)}`,
  calendar: '#calendar',
  calendarWeek: (date: string) => `#calendar/${date}`,
  trends: '#trends',
  settings: '#settings',
  activity: (id: string) => `#activity/${encodeURIComponent(id)}`,
} as const
