export const WEEKLY_PROMPT =
  'Use $going-bananas-coach for my Sunday review in real mode. Review my current block and talk through the plan with me. My schedule changes and feedback are: …'
export const EXCEPTION_PROMPT =
  'Use $going-bananas-coach for an exception review. Read the open findings in the app and patch only what they require.'
export const BLOCK_PROMPT =
  'Use $going-bananas-coach for a block review. An exception needs a bigger review.'
export const BENCHMARK_PROMPT =
  'Use $going-bananas-coach for a block review. Review the block benchmark.'
export const REASSESS_PROMPT = 'Use $going-bananas-coach to reassess the open exception patch.'
export const racePrompt = (eventName: string, eventDate: string): string =>
  `Use $going-bananas-coach for a post-race review of ${eventName} on ${eventDate}.`
export const INTERRUPTION_PROMPT =
  'Use $going-bananas-coach to review my saved running interruption and return. Read the accepted calendar and recent sessions, talk through what to leave behind and the first feasible run. When we agree on changes, revise the current draft if there is one.'
