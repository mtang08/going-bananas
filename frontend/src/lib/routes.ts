export const pageHref = {
  home: '#home',
  calendar: '#calendar',
  calendarWeek: (date: string) => `#calendar/${date}`,
  trends: '#trends',
  settings: '#settings',
  activity: (id: string) => `#activity/${encodeURIComponent(id)}`,
} as const
