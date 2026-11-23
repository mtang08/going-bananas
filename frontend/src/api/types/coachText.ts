export type WhyKind = 'observation' | 'research' | 'inference' | 'priority'
export interface Why {
  kind: WhyKind
  text: string
}
export interface Rule {
  when: string
  then: string
}
export interface CitedSource {
  kind: 'policy' | 'evidence'
  title: string
  papers: string[]
}
