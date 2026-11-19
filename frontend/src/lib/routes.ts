export const pageHref = {
  home: '#home',
  calendar: '#calendar',
  trends: '#trends',
  settings: '#settings',
  activity: (id: string) => `#activity/${encodeURIComponent(id)}`,
} as const
