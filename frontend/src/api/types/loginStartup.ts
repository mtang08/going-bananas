export interface LoginStartup {
  status: 'enabled' | 'disabled' | 'unsupported' | 'other_checkout' | 'unavailable'
  enabled: boolean | null
  message: string | null
}
